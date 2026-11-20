"""文本分块领域服务：将页面长文本切分为语义单元。

补录清单（文本补录）约定：
- 情感标注批量送入的块若在分块表找不到，登记一条「待补录」补录项，
  记录原批次ID、来源页面（若可追溯）与文本版本，保证缺块请求不丢失。
- 工作台按补录项逐条找回缺块（补回原块标识），状态转「已补录」，
  随后可引用原批次重新交付情感分析。
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


BLOCK_TYPES = ["paragraph", "heading", "list_item", "table_cell", "code_block", "quote"]

# 补录状态。保留在 STATUS_ORDER 中，列表 status 过滤与工作台都能直接用。
SUPPLEMENT_PENDING = "待补录"
SUPPLEMENT_RESOLVED = "已补录"


class TextSegmentService(BaseModuleService):
    MODULE = "text_segment"
    ENTITY = "文本块"
    OPERATION_TERM = "入库"
    LIST_FIELDS = ["块ID", "来源页面", "块类型", "起始位置", "结束位置", "字符长度", "语言标识"]
    REQUIRED_FIELDS = ["块ID", "来源页面", "块类型"]
    STATUS_ORDER = ["已切分", "已标注", "已入库", "已丢弃", SUPPLEMENT_PENDING]
    ACTION_RULES = {"标注语义": "已切分", "确认入库": "已标注", "丢弃无用": "已切分"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------ 页面切分
    def segment_page(self, page_url: str, raw_html: str = "") -> dict[str, Any]:
        """模拟页面文本分块：从调度模块获得URL后切分为语义块并入库。"""
        if not raw_html:
            raw_html = f"<html><body><h1>Page Title</h1><p>Content paragraph for {page_url}</p><ul><li>Item A</li><li>Item B</li></ul></body></html>"

        blocks = []
        positions = [("h1", 0, 50), ("p", 60, 300), ("li", 310, 350), ("li", 355, 395)]
        rows = store.rows(self.MODULE)
        existing_ids = {r.get("块ID") for r in rows}
        for i, (tag, start, end) in enumerate(positions):
            btype = "heading" if tag == "h1" else ("list_item" if tag == "li" else "paragraph")
            block_id = hashlib.md5(f"{page_url}|{tag}|{i}".encode()).hexdigest()[:8]
            if block_id in existing_ids:
                # 同一页面重复切分：不重复入库，直接带回已有块。
                blocks.append(next(r for r in rows if r.get("块ID") == block_id))
                continue
            char_len = end - start
            entry = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "status": "已切分",
                "pending": True,
                "abnormal": False,
                "块ID": block_id,
                "来源页面": page_url,
                "块类型": btype,
                "起始位置": str(start),
                "结束位置": str(end),
                "字符长度": str(char_len),
                "语言标识": "zh-CN",
                "text_sample": f"[{btype}] Content from {page_url} position {start}-{end}",
            }
            rows.append(entry)
            existing_ids.add(block_id)
            blocks.append(entry)
        return {
            "ok": True,
            "page_url": page_url,
            "block_count": len(blocks),
            "total_chars": sum(int(b["字符长度"]) for b in blocks),
            "blocks": blocks,
        }

    def feed_sentiment_tag(self, block_ids: list[str]) -> dict[str, Any]:
        """将文本块提供给情感标注进行情感分析。"""
        blocks = []
        missing = []
        for bid in block_ids:
            row = next(
                (
                    r for r in store.rows(self.MODULE)
                    if r.get("块ID") == bid and r.get("status") != SUPPLEMENT_PENDING
                ),
                None,
            )
            if row:
                blocks.append({
                    "block_id": bid,
                    "source_page": row.get("来源页面"),
                    "block_type": row.get("块类型"),
                    "text_sample": row.get("text_sample", row.get("块ID", "")),
                })
            else:
                # 缺块不再静默：回执里明确列出，便于上游决定是否登记补录。
                missing.append({"block_id": bid, "status": SUPPLEMENT_PENDING})
        return {
            "ok": True,
            "input_blocks": len(block_ids),
            "matched_blocks": len(blocks),
            "missing_blocks": missing,
            "blocks": blocks,
        }

    # ------------------------------------------------------------------ 补录清单
    def _supplement_table(self) -> list[dict[str, Any]]:
        return store.rows("text_supplement")

    def _next_supplement_id(self) -> str:
        table = self._supplement_table()
        seq = max((int(s.get("seq", 0)) for s in table), default=0) + 1
        # 全局唯一：服务重启后旧补录引用不会与新补录项撞号。
        return f"sup-{seq:04d}-{uuid.uuid4().hex[:8]}"

    def register_missing_block(
        self,
        block_id: str,
        *,
        batch_id: str | None = None,
        source_page: str | None = None,
        text_version: str | None = None,
    ) -> dict[str, Any]:
        """登记缺块到文本补录清单；同一缺块在同一批次只登记一次。

        若分块表已存在同ID占位（待补录）行则复用，否则创建占位行，
        保证后续 segment/补录可以凭原块标识找回。
        """
        table = self._supplement_table()
        existing = next(
            (
                s for s in table
                if s.get("块ID") == block_id
                and s.get("状态") == SUPPLEMENT_PENDING
            ),
            None,
        )
        if existing is not None:
            if batch_id and batch_id not in existing.get("关联批次", []):
                existing.setdefault("关联批次", []).append(batch_id)
            return existing

        seq = len(table) + 1
        entry = {
            "id": seq,
            "seq": seq,
            "补录ID": self._next_supplement_id(),
            "块ID": block_id,
            "来源页面": source_page or "",
            "原批次ID": batch_id or "",
            "关联批次": [batch_id] if batch_id else [],
            "文本版本": text_version or "",
            "状态": SUPPLEMENT_PENDING,
            "登记原因": "批量情感分析未找到文本块",
        }
        table.append(entry)

        # 分块表占位：工作台与列表都能看到这块待补录，且不会被误当成正常块计数。
        segment_rows = store.rows(self.MODULE)
        placeholder = next((r for r in segment_rows if r.get("块ID") == block_id), None)
        if placeholder is None:
            segment_rows.append({
                "id": max((int(row.get("id", 0)) for row in segment_rows), default=0) + 1,
                "status": SUPPLEMENT_PENDING,
                "pending": True,
                "abnormal": True,
                "块ID": block_id,
                "来源页面": source_page or "来源待补录",
                "块类型": "unknown",
                "起始位置": "",
                "结束位置": "",
                "字符长度": "0",
                "语言标识": "",
                "text_sample": "",
                "补录ID": entry["补录ID"],
            })
        return entry

    def list_supplements(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = self._supplement_table()
        if status:
            rows = [r for r in rows if r.get("状态") == status]
        return list(rows)

    def list_pending_supplements(self) -> list[dict[str, Any]]:
        return self.list_supplements(SUPPLEMENT_PENDING)

    def get_supplement(self, supplement_id: str) -> dict[str, Any] | None:
        return next(
            (s for s in self._supplement_table() if s.get("补录ID") == supplement_id),
            None,
        )

    def restore_missing_block(
        self,
        supplement_id: str,
        *,
        source_page: str | None = None,
        block_type: str | None = None,
        text_sample: str | None = None,
    ) -> dict[str, Any]:
        """工作台按补录项逐条找回缺块：补回原块标识与内容，占位行转正。"""
        supplement = self.get_supplement(supplement_id)
        if supplement is None:
            return {"ok": False, "message": f"补录项 {supplement_id} 不存在"}
        block_id = supplement["块ID"]
        rows = store.rows(self.MODULE)
        placeholder = next((r for r in rows if r.get("块ID") == block_id), None)
        page = source_page or supplement.get("来源页面") or "来源待补录"
        sample = text_sample or f"[restored] 补录文本块 {block_id} from {page}"
        version = hashlib.md5(sample.encode("utf-8")).hexdigest()[:12]
        if placeholder is None:
            placeholder = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "块ID": block_id,
            }
            rows.append(placeholder)
        placeholder.update({
            "status": "已切分",
            "pending": True,
            "abnormal": False,
            "来源页面": page,
            "块类型": block_type or placeholder.get("块类型") or "paragraph",
            "起始位置": placeholder.get("起始位置") or "0",
            "结束位置": placeholder.get("结束位置") or str(len(sample)),
            "字符长度": placeholder.get("字符长度") or str(len(sample)),
            "语言标识": placeholder.get("语言标识") or "zh-CN",
            "text_sample": sample,
        })
        # 块内容已找回，但情感分析尚未重投交付，补录项保持「待补录」，
        # 由 SentimentTagService.redeliver_supplement 成功后回写为「已补录」。
        supplement["来源页面"] = page
        supplement["文本版本"] = version
        supplement["块内容已找回"] = True
        return {"ok": True, "supplement": supplement, "block": placeholder}

    def mark_supplement_resolved(
        self,
        supplement_id: str,
        *,
        record_id: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """补录块重投成功后回写补录清单：关联情感记录与交付批次。"""
        supplement = self.get_supplement(supplement_id)
        if supplement is None:
            return {"ok": False, "message": f"补录项 {supplement_id} 不存在"}
        supplement["状态"] = SUPPLEMENT_RESOLVED
        if record_id:
            supplement["情感记录ID"] = record_id
        if batch_id:
            supplement["交付批次ID"] = batch_id
            if batch_id not in supplement.setdefault("关联批次", []):
                supplement["关联批次"].append(batch_id)
        return {"ok": True, "supplement": supplement}

    # ------------------------------------------------------------------ 统计
    def compute_segment_stats(self) -> dict[str, Any]:
        """分块统计，供抽取指标消费。待补录占位块单独统计，不计入正常块。"""
        rows = store.rows(self.MODULE)
        type_dist: dict[str, int] = {}
        total_chars = 0
        pending_supplement = 0
        normal_rows: list[dict[str, Any]] = []
        for row in rows:
            if row.get("status") == SUPPLEMENT_PENDING:
                pending_supplement += 1
                continue
            normal_rows.append(row)
            btype = row.get("块类型", "unknown")
            type_dist[btype] = type_dist.get(btype, 0) + 1
            try:
                total_chars += int(row.get("字符长度", "0"))
            except (ValueError, TypeError):
                pass
        return {
            "total_blocks": len(normal_rows),
            "pending_supplement_blocks": pending_supplement,
            "total_chars": total_chars,
            "avg_chars_per_block": round(total_chars / len(normal_rows)) if normal_rows else 0,
            "block_type_distribution": type_dist,
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["segment_stats"] = self.compute_segment_stats()
        base["supplement_pending"] = len(self.list_pending_supplements())
        return base
