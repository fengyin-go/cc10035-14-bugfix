"""情感标注领域服务：对文本片段进行情感倾向标注。

关键约定（逐条处理缺块回执场景）：
- 批量送入的块逐块校验来源，未找到的块生成缺块回执并登记到文本分块补录清单，
  原批次汇总不再静默丢弃这部分请求，缺块也绝不计入中性。
- 同一个块（按块ID+文本版本去重）即使重复送达，情感分布只参与一次计数。
- 中断后重试可凭块ID与文本版本区分「已分析」和「待补录」，重投只补缺口。
- 每个批次标注实际覆盖的页面与参与计数的块，发布统计与补录清单覆盖范围一致。
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from app.services.base import BaseModuleService
from app.services.text_segment import SUPPLEMENT_PENDING, TextSegmentService
from app.store import store


SENTIMENT_LABELS = ["positive", "negative", "neutral", "mixed"]
ASPECT_SENTIMENTS = {
    "价格": ["positive", "negative", "neutral"],
    "质量": ["positive", "negative", "neutral"],
    "服务": ["positive", "negative", "neutral"],
    "交付": ["positive", "negative", "neutral"],
}

# 情感记录（store 表 sentiment_tag 行）上记录来源块与文本版本的字段。
FIELD_BLOCK_ID = "来源块ID"
FIELD_PAGE = "来源页面"
FIELD_TEXT_VERSION = "文本版本"
FIELD_BATCH_ID = "批次ID"


def text_version_of(block: dict[str, Any]) -> str:
    """根据文本块当前内容计算文本版本；内容不变则版本稳定，重投天然幂等。"""
    sample = str(block.get("text_sample") or block.get("块ID") or "")
    return hashlib.md5(sample.encode("utf-8")).hexdigest()[:12]


class SentimentTagService(BaseModuleService):
    MODULE = "sentiment_tag"
    ENTITY = "情感记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = [
        "记录ID", "文本片段", "情感倾向", "强烈程度", "方面词", "方面情感",
        "标注模型", FIELD_BLOCK_ID, FIELD_PAGE, FIELD_TEXT_VERSION, FIELD_BATCH_ID,
    ]
    REQUIRED_FIELDS = ["记录ID", "文本片段", "情感倾向"]
    STATUS_ORDER = ["已标注", "已复核", "已修正", "已忽略"]
    ACTION_RULES = {"复核标注": "已标注", "修正标注": "已标注", "忽略标注": "已标注"}
    NEGATIVE_ACTIONS = ["忽略标注"]

    # ------------------------------------------------------------------ 内部状态
    def _batch_table(self) -> list[dict[str, Any]]:
        """逐块情感批次数据集（独立于情感记录表，保留逐块交付回执）。"""
        return store.rows("sentiment_batches")

    def _next_batch_seq(self) -> int:
        table = self._batch_table()
        return max((int(b.get("seq", 0)) for b in table), default=0) + 1

    @staticmethod
    def _new_batch_id(seq: int) -> str:
        # 全局唯一：服务重启或表被清空后，旧补录项引用的原批次ID也不会撞号。
        return f"batch-{seq:04d}-{uuid.uuid4().hex[:8]}"

    def _find_block(self, block_id: str) -> dict[str, Any] | None:
        # 待补录占位行只是补录清单的锚点，内容未找回，不能当作可分析的真实块。
        return next(
            (
                r for r in store.rows("text_segment")
                if r.get("块ID") == block_id and r.get("status") != SUPPLEMENT_PENDING
            ),
            None,
        )

    def _find_sentiment_row(
        self, block_id: str, text_version: str
    ) -> dict[str, Any] | None:
        """按 块ID+文本版本 定位已分析记录：重试/重投的幂等依据。"""
        return next(
            (
                r for r in store.rows(self.MODULE)
                if r.get(FIELD_BLOCK_ID) == block_id
                and r.get(FIELD_TEXT_VERSION) == text_version
            ),
            None,
        )

    # ------------------------------------------------------------------ 单块分析
    def analyze_sentiment(
        self,
        text_segment_block_id: str,
        *,
        batch_id: str | None = None,
        text_version: str | None = None,
    ) -> dict[str, Any]:
        """分析单个文本块的情感：消费文本分块输出。

        块不存在时返回结构化缺块回执（ok=False、reason、block_id），
        由批量流程登记补录清单，调用方不得把缺块当中性处理。
        """
        block = self._find_block(text_segment_block_id)
        if block is None:
            return {
                "ok": False,
                "reason": "文本块不存在",
                "block_id": text_segment_block_id,
                "status": "待补录",
            }

        version = text_version or text_version_of(block)
        existing = self._find_sentiment_row(text_segment_block_id, version)
        if existing is not None:
            # 同一块同一文本版本重复送达：复用结果，不重复计数。
            return {
                "ok": True,
                "duplicate": True,
                "记录ID": existing["记录ID"],
                "文本片段": existing["文本片段"],
                "情感倾向": existing["情感倾向"],
                "强烈程度": existing["强烈程度"],
                "方面词": existing["方面词"],
                "方面情感": existing["方面情感"],
                "标注模型": existing["标注模型"],
                FIELD_BLOCK_ID: text_segment_block_id,
                FIELD_PAGE: existing.get(FIELD_PAGE),
                FIELD_TEXT_VERSION: version,
            }

        text_hash = int(hashlib.md5(text_segment_block_id.encode()).hexdigest()[:4], 16)
        mood_idx = text_hash % len(SENTIMENT_LABELS)
        sentiment = SENTIMENT_LABELS[mood_idx]
        intensity = ["低", "中", "高", "极高"][text_hash % 4]
        aspects = list(ASPECT_SENTIMENTS.keys())
        aspect_idx = text_hash % len(aspects)
        aspect = aspects[aspect_idx]
        aspect_sent = ASPECT_SENTIMENTS[aspect][text_hash % 3]

        return {
            "ok": True,
            "duplicate": False,
            "记录ID": f"sent-{text_segment_block_id}",
            "文本片段": f"Text from block {text_segment_block_id}",
            "情感倾向": sentiment,
            "强烈程度": intensity,
            "方面词": aspect,
            "方面情感": aspect_sent,
            "标注模型": "sentiment-analyzer-v2",
            FIELD_BLOCK_ID: text_segment_block_id,
            FIELD_PAGE: block.get("来源页面"),
            FIELD_TEXT_VERSION: version,
            FIELD_BATCH_ID: batch_id,
        }

    # ------------------------------------------------------------------ 批量交付
    def batch_analyze(
        self,
        text_block_ids: list[str],
        *,
        batch_id: str | None = None,
        text_versions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """批量情感分析，交付逐块情感批次数据集。

        - 逐块校验来源：找到的块分析/复用，未找到的块出缺块回执并登记补录清单。
        - 去重：请求内重复块、历史已分析的同版本块都只保留一份参与计数。
        - 覆盖范围：返回实际覆盖页面、参与计数块、待补录块，统计与补录清单对得上。
        """
        text_versions = text_versions or {}
        seq = self._next_batch_seq()
        bid = batch_id or self._new_batch_id(seq)
        segment_service = TextSegmentService()

        receipts: list[dict[str, Any]] = []
        seen_in_request: set[str] = set()
        covered_pages: set[str] = set()
        duplicate_count = 0

        # 请求内先按块ID去重，保留首次出现的顺序。
        ordered_unique: list[str] = []
        for raw_id in text_block_ids:
            block_id = str(raw_id or "").strip()
            if not block_id:
                continue
            if block_id not in seen_in_request:
                seen_in_request.add(block_id)
                ordered_unique.append(block_id)

        for block_id in ordered_unique:
            block = self._find_block(block_id)
            if block is None:
                # 缺块：登记文本补录清单，并给出明确回执，绝不计入中性。
                supplement = segment_service.register_missing_block(
                    block_id, batch_id=bid, text_version=text_versions.get(block_id)
                )
                missing_receipt = {
                    "block_id": block_id,
                    "source_page": supplement.get("source_page"),
                    "status": "待补录",
                    "found": False,
                    "duplicate": False,
                    "reason": "文本块不存在，已登记补录清单",
                    "supplement_id": supplement["补录ID"],
                }
                receipts.append(missing_receipt)
                continue

            version = text_versions.get(block_id) or text_version_of(block)
            result = self.analyze_sentiment(
                block_id, batch_id=bid, text_version=version
            )
            is_duplicate = bool(result.get("duplicate"))
            if is_duplicate:
                duplicate_count += 1
            else:
                self._persist_sentiment_row(result)
            page = block.get("来源页面")
            if page:
                covered_pages.add(page)
            receipts.append({
                "block_id": block_id,
                "source_page": page,
                "text_version": version,
                "status": "已分析",
                "found": True,
                "duplicate": is_duplicate,
                "记录ID": result["记录ID"],
                "情感倾向": result["情感倾向"],
                "强烈程度": result["强烈程度"],
                "方面词": result["方面词"],
                "方面情感": result["方面情感"],
            })

        dataset = self._upsert_dataset(
            bid=bid,
            seq=seq,
            request_count=len(text_block_ids),
            receipts=receipts,
        )
        counted = [r for r in dataset["逐块回执"] if r.get("found")]
        return {
            "ok": True,
            "批次ID": bid,
            "total_analyzed": len(counted),
            "missing_count": dataset["待补录块数"],
            "duplicate_count": duplicate_count,
            "covered_pages": list(dataset["覆盖页面"]),
            "sentiment_distribution": dict(dataset["情感分布"]),
            "block_receipts": receipts,
            "dataset": dataset,
        }

    def _upsert_dataset(
        self,
        *,
        bid: str,
        seq: int,
        request_count: int,
        receipts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """写入或更新批次数据集。

        引用同一批次ID重投（补录重交付）时原地合并逐块回执并重新计算覆盖范围，
        不产生重复批次记录，保证发布统计与补录清单始终对得上。
        """
        table = self._batch_table()
        existing = next((b for b in table if b.get("批次ID") == bid), None)
        if existing is not None:
            merged = {r["block_id"]: r for r in existing.get("逐块回执", [])}
            for receipt in receipts:
                # 新回执优先：待补录块被补回后，已分析回执替换旧的缺块回执。
                merged[receipt["block_id"]] = receipt
            all_receipts = list(merged.values())
            existing["请求块数"] = max(existing.get("请求块数", 0), request_count)
            existing["去重后块数"] = len(merged)
        else:
            all_receipts = receipts
            existing = {"seq": seq, "批次ID": bid}
            table.append(existing)

        counted = [r for r in all_receipts if r.get("found")]
        missing = [r for r in all_receipts if not r.get("found")]
        pages = sorted({r.get("source_page") for r in counted if r.get("source_page")})
        existing.update({
            "已分析块数": len({r["block_id"] for r in counted}),
            "参与计数块数": len(counted),
            # 重复送达在分布层面已按块去重；这里回执里保留每次送达的重复标记。
            "重复送达块数": sum(1 for r in all_receipts if r.get("duplicate")),
            "待补录块数": len(missing),
            "覆盖页面": pages,
            "覆盖页面数": len(pages),
            "情感分布": {
                label: sum(1 for r in counted if r.get("情感倾向") == label)
                for label in SENTIMENT_LABELS
            },
            "待补录块": [r["block_id"] for r in missing],
            "逐块回执": all_receipts,
            "delivered": not missing,
        })
        return existing

    def _persist_sentiment_row(self, result: dict[str, Any]) -> dict[str, Any]:
        """把单块分析结果写成情感记录；同块同版本已存在则不新增。"""
        rows = store.rows(self.MODULE)
        existing = self._find_sentiment_row(
            result[FIELD_BLOCK_ID], result[FIELD_TEXT_VERSION]
        )
        if existing is not None:
            return existing
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": self.STATUS_ORDER[0],
            "pending": True,
            "abnormal": False,
            "记录ID": result["记录ID"],
            "文本片段": result["文本片段"],
            "情感倾向": result["情感倾向"],
            "强烈程度": result["强烈程度"],
            "方面词": result["方面词"],
            "方面情感": result["方面情感"],
            "标注模型": result["标注模型"],
            FIELD_BLOCK_ID: result[FIELD_BLOCK_ID],
            FIELD_PAGE: result.get(FIELD_PAGE),
            FIELD_TEXT_VERSION: result[FIELD_TEXT_VERSION],
            FIELD_BATCH_ID: result.get(FIELD_BATCH_ID),
        }
        rows.append(entry)
        return entry

    # ------------------------------------------------------------------ 补录重投
    def redeliver_supplement(self, supplement_id: str) -> dict[str, Any]:
        """文本分块工作台补回缺块后调用：引用原批次重新交付该块。"""
        segment_service = TextSegmentService()
        supplement = segment_service.get_supplement(supplement_id)
        if supplement is None:
            return {"ok": False, "message": f"补录项 {supplement_id} 不存在"}
        if supplement.get("状态") != "待补录":
            return {
                "ok": False,
                "message": f"补录项 {supplement_id} 状态为{supplement.get('状态')}，无需重投",
            }

        block_id = supplement["块ID"]
        block = self._find_block(block_id)
        if block is None:
            return {"ok": False, "message": f"文本块 {block_id} 仍未补回，无法重投"}

        original_batch = supplement.get("原批次ID")
        result = self.batch_analyze(
            [block_id],
            batch_id=original_batch,
            text_versions={block_id: supplement.get("文本版本") or text_version_of(block)},
        )
        receipt = next(
            (r for r in result["block_receipts"] if r["block_id"] == block_id), None
        )
        if receipt and receipt.get("found"):
            segment_service.mark_supplement_resolved(
                supplement_id,
                record_id=receipt.get("记录ID"),
                batch_id=result["批次ID"],
            )
        return result

    # ------------------------------------------------------------------ 查询视图
    def list_batches(self) -> list[dict[str, Any]]:
        """逐块情感批次数据集列表。"""
        return list(self._batch_table())

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        return next(
            (b for b in self._batch_table() if b.get("批次ID") == batch_id), None
        )

    def negative_blocks_for_review(self, batch_id: str | None = None) -> list[dict[str, Any]]:
        """供值班员从已发布情感分布进入：列出可复查的负向块（只含已分析块）。"""
        datasets = self._batch_table()
        if batch_id:
            datasets = [b for b in datasets if b.get("批次ID") == batch_id]
        negatives: list[dict[str, Any]] = []
        seen_blocks: set[str] = set()
        for dataset in datasets:
            for receipt in dataset.get("逐块回执", []):
                if receipt.get("found") and receipt.get("情感倾向") == "negative":
                    if receipt["block_id"] in seen_blocks:
                        continue
                    seen_blocks.add(receipt["block_id"])
                    negatives.append({
                        **receipt,
                        "批次ID": dataset.get("批次ID"),
                    })
        return negatives

    def compute_sentiment_summary(self) -> dict[str, Any]:
        """情感分布摘要，供聚合视图消费。

        分布只统计真实情感记录（缺块没有记录，天然不会被算成中性），
        并标明实际覆盖的页面与参与计数的块；同块同版本只保留一条记录。
        """
        rows = store.rows(self.MODULE)
        dist: dict[str, int] = {}
        intensity_dist: dict[str, int] = {}
        # 去重键：有来源块的按 块ID+文本版本（同块不同版本各自计数，同版本只算一次）；
        # 无来源块的历史记录按记录ID单独保留。
        counted_keys: set[str] = set()
        covered_pages: set[str] = set()
        for row in rows:
            block_id = row.get(FIELD_BLOCK_ID)
            version = row.get(FIELD_TEXT_VERSION)
            dedup_key = f"{block_id}|{version}" if block_id else f"record|{row.get('记录ID')}"
            if dedup_key in counted_keys:
                continue
            counted_keys.add(dedup_key)
            sent = row.get("情感倾向", "未知")
            dist[sent] = dist.get(sent, 0) + 1
            intensity = row.get("强烈程度", "未知")
            intensity_dist[intensity] = intensity_dist.get(intensity, 0) + 1
            page = row.get(FIELD_PAGE)
            if page:
                covered_pages.add(page)

        segment_service = TextSegmentService()
        pending_supplements = segment_service.list_pending_supplements()
        return {
            "total_records": len(rows),
            "counted_block_count": len(counted_keys),
            "sentiment_distribution": dist,
            "intensity_distribution": intensity_dist,
            "covered_pages": sorted(covered_pages),
            "covered_page_count": len(covered_pages),
            "pending_supplement_count": len(pending_supplements),
            "pending_supplement_blocks": [s["块ID"] for s in pending_supplements],
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["sentiment_summary"] = self.compute_sentiment_summary()
        base["batch_datasets"] = len(self._batch_table())
        return base
