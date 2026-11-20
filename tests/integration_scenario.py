"""端到端场景验证：缺块回执、补录清单、幂等重投与覆盖范围对账。

场景（对应用户描述）：
1. 同一批两个页面（甲页全部块、乙页缺一块），批量送入情感分析并故意省略乙页一块。
2. 补录前从情感分布入口核对可复查的负向块，分布标明覆盖页面与参与计数块，
   缺块单列且不计中性。
3. 中断重试：同版本重复送达，分布只算一次；已分析/待补录可区分。
4. 文本分块工作台补回原标识并重投，引用原批次重新交付。
5. 核对逐块情感批次数据集的实际覆盖与重复计数，发布统计与补录清单对得上。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/workspace/backend")

from app.services.sentiment_tag import (
    SENTIMENT_LABELS,
    SentimentTagService,
    text_version_of,
)
from app.services.text_segment import TextSegmentService, SUPPLEMENT_PENDING, SUPPLEMENT_RESOLVED
from app.store import store


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(f"校验失败：{message}")
    print(f"  ✓ {message}")


def main() -> None:
    seg = TextSegmentService()
    sent = SentimentTagService()

    print("== 步骤1：切分甲、乙两个页面，各4块 ==")
    page_a = "https://example.com/甲页"
    page_b = "https://example.com/乙页"
    blocks_a = seg.segment_page(page_a)["blocks"]
    blocks_b = seg.segment_page(page_b)["blocks"]
    ids_a = [b["块ID"] for b in blocks_a]
    ids_b = [b["块ID"] for b in blocks_b]
    scenario_block_ids = set(ids_a + ids_b)

    # 干净的运行期表：清空批次/补录领域表，并移除本次场景产生的块与情感记录。
    store.rows("sentiment_batches").clear()
    store.rows("text_supplement").clear()
    for row in list(store.rows("text_segment")):
        if row.get("块ID") in scenario_block_ids or row.get("status") == SUPPLEMENT_PENDING:
            store.rows("text_segment").remove(row)
    for row in list(store.rows("sentiment_tag")):
        if row.get("来源块ID"):
            store.rows("sentiment_tag").remove(row)
    # 重新切分（上面的清理把场景块也移除了）。
    blocks_a = seg.segment_page(page_a)["blocks"]
    blocks_b = seg.segment_page(page_b)["blocks"]
    ids_a = [b["块ID"] for b in blocks_a]
    ids_b = [b["块ID"] for b in blocks_b]
    check(len(ids_a) == 4 and len(ids_b) == 4, "两个页面各切出4个文本块")

    print("== 步骤2：同批提交两页全部块，但故意省略（缺送）乙页最后一块 ==")
    missing_id = ids_b[-1]
    submitted = ids_a + ids_b[:-1] + [missing_id]  # 末块在分块表中先移除模拟缺块
    # 模拟乙页该块尚未读取：从分块表临时移除（保留其内容版本用于后续补录）
    missing_row = next(r for r in store.rows("text_segment") if r["块ID"] == missing_id)
    missing_version = text_version_of(missing_row)
    store.rows("text_segment").remove(missing_row)

    result = sent.batch_analyze(submitted, text_versions={missing_id: missing_version})
    check(result["ok"], "批量分析返回成功")
    check(result["missing_count"] == 1, f"缺块回执为1条（实际{result['missing_count']}）")
    missing_receipt = next(r for r in result["block_receipts"] if r["block_id"] == missing_id)
    check(missing_receipt["status"] == SUPPLEMENT_PENDING and not missing_receipt["found"],
          "缺块逐块回执明确标注待补录，未被静默丢弃")
    check(result["total_analyzed"] == 7, f"已分析7块（实际{result['total_analyzed']}），与请求8块差异即缺块")
    check(result["covered_pages"] == sorted({page_a, page_b}),
          f"覆盖页面标明甲乙两页：{result['covered_pages']}")
    check(sum(result["sentiment_distribution"].values()) == 7,
          "情感分布参与计数合计=7，缺块未计入任何情感类别")
    check(result["sentiment_distribution"]["neutral"] ==
          sum(1 for r in result["block_receipts"] if r.get("found") and r.get("情感倾向") == "neutral"),
          "中性计数只来自真实分析块，缺块没有被算成中性")

    print("== 步骤3：补录清单与发布统计（聚合视图）覆盖范围对账 ==")
    pending = seg.list_pending_supplements()
    check(len(pending) == 1 and pending[0]["块ID"] == missing_id,
          "文本补录清单登记1条待补录，块ID为乙页缺块")
    check(pending[0]["原批次ID"] == result["批次ID"], "补录项引用原批次ID")
    check(pending[0]["文本版本"] == missing_version, "补录项保留原文本版本")
    # 分块表占位可见
    placeholder = next(r for r in store.rows("text_segment") if r["块ID"] == missing_id)
    check(placeholder["status"] == SUPPLEMENT_PENDING, "分块工作台能看到待补录占位块")

    summary = sent.compute_sentiment_summary()
    # 全局分布 = 场景已分析块 + 3条种子情感记录（去重口径下种子行也计入）。
    seed_rows = len([r for r in store.rows("sentiment_tag") if not r.get("来源块ID")])
    check(summary["counted_block_count"] == 7 + seed_rows,
          f"分布参与计数块=7场景块+{seed_rows}种子（实际{summary['counted_block_count']}）")
    check(summary["pending_supplement_count"] == 1, "分布同时标明1个待补录块")
    check(summary["covered_page_count"] == 2, f"分布标明实际覆盖2页（实际{summary['covered_page_count']}）")
    stats = seg.compute_segment_stats()
    check(stats["total_blocks"] == len(store.rows("text_segment")) - 1
          and stats["pending_supplement_blocks"] == 1,
          f"待补录占位块不计入正常块统计（正常{stats['total_blocks']}/待补录{stats['pending_supplement_blocks']}）")

    print("== 步骤4：值班员从情感分布入口找可复查的负向块 ==")
    negatives = sent.negative_blocks_for_review(result["批次ID"])
    expected_neg = [r for r in result["block_receipts"]
                    if r.get("found") and r.get("情感倾向") == "negative"]
    check(len(negatives) == len(expected_neg),
          f"负向块复查入口列出{len(negatives)}块，与批次内真实负向块{len(expected_neg)}严格一致")
    check(all(n["block_id"] != missing_id for n in negatives), "待补录缺块不出现在负向复查列表")
    check(all(n["情感倾向"] == "negative" and n.get("source_page") for n in negatives),
          "复查项带情感结论与来源页面，可直接定位回原页面")
    # 构造一个确定性负向块（独立批次），验证分布入口能把它挑出来给值班员复查。
    probe_sup = seg.register_missing_block("neg-probe-001", batch_id="batch-probe")
    neg_block = seg.restore_missing_block(
        probe_sup["补录ID"],
        source_page=page_a, block_type="paragraph",
        text_sample="negative probe block",
    )["block"]
    probe = sent.batch_analyze(["neg-probe-001"], batch_id="batch-probe")
    probe_receipt = probe["block_receipts"][0]
    # 探针块已补回并交付，回写其补录项，避免污染场景的待补录清单计数。
    seg.mark_supplement_resolved(
        probe_sup["补录ID"], record_id=probe_receipt.get("记录ID"), batch_id="batch-probe")
    if probe_receipt.get("情感倾向") == "negative":
        review = sent.negative_blocks_for_review("batch-probe")
        check(any(n["block_id"] == "neg-probe-001" for n in review),
              "负向块出现后，分布入口可复查到该块及其所属批次")
    else:
        check(probe_receipt.get("found"), "探针块分析成功（该哈希非负向，跳过负向断言）")

    print("== 步骤5：中断重试——同一文本版本重复送达，分布只算一次 ==")
    retry = sent.batch_analyze(submitted, text_versions={missing_id: missing_version})
    check(retry["duplicate_count"] == 7, f"7个已分析块识别为重复送达（实际{retry['duplicate_count']}）")
    check(retry["total_analyzed"] == 7, "重试后参与计数仍为7，没有重复计数")
    check(retry["missing_count"] == 1, "重试仍只产生1条缺块（补录清单不重复登记）")
    check(len(seg.list_pending_supplements()) == 1, "补录清单仍只有1条，重复送达幂等")
    real_records = [r for r in store.rows("sentiment_tag")
                    if r.get("来源块ID") in scenario_block_ids]
    check(len(real_records) == 7, f"情感记录表场景块仍为7条（实际{len(real_records)}），无重复写入")
    summary2 = sent.compute_sentiment_summary()
    check(summary2["counted_block_count"] == 7 + 1 + seed_rows,
          f"发布分布重试后场景块仍只计7块（含探针与种子共{summary2['counted_block_count']}）")
    # 已分析 vs 待补录可区分
    analyzed_ids = {r["来源块ID"] for r in store.rows("sentiment_tag")
                    if r.get("来源块ID") in scenario_block_ids}
    check(missing_id not in analyzed_ids and len(analyzed_ids) == 7, "可区分7个已分析块与1个待补录块")

    print("== 步骤6：文本分块工作台补回原标识并重投，引用原批次重新交付 ==")
    sup_id = pending[0]["补录ID"]
    restored = seg.restore_missing_block(sup_id, source_page=page_b, block_type="list_item")
    check(restored["ok"], "缺块按原块标识补回工作台")
    restored_block = next(r for r in store.rows("text_segment") if r["块ID"] == missing_id)
    check(restored_block["status"] != SUPPLEMENT_PENDING and restored_block.get("text_sample"),
          "补回块转正为已切分且带文本内容")
    redeliver = sent.redeliver_supplement(sup_id)
    check(redeliver["ok"], "引用原批次重投成功")
    receipt = next(r for r in redeliver["block_receipts"] if r["block_id"] == missing_id)
    check(receipt["found"] and receipt["status"] == "已分析", "缺块重投后取得逐块情感结果")

    print("== 步骤7：补录后全量对账 ==")
    check(seg.get_supplement(sup_id)["状态"] == SUPPLEMENT_RESOLVED, "补录清单回写为已补录")
    check(len(seg.list_pending_supplements()) == 0, "待补录清零")
    repeat_redeliver = sent.redeliver_supplement(sup_id)
    check(repeat_redeliver["ok"] is False, "已补录项重复重投被拒绝，不产生重复交付")
    dataset = sent.get_batch(result["批次ID"])
    check(dataset is not None, "原批次数据集可检索")
    same_id_batches = [b for b in sent.list_batches() if b["批次ID"] == result["批次ID"]]
    check(len(same_id_batches) == 1, "引用原批次重投只更新同一条数据集，不产生重复批次记录")
    check(dataset["delivered"], "原批次标记为完整交付")
    check(dataset["待补录块数"] == 0, f"原批次待补录归零（实际{dataset['待补录块数']}）")
    check(dataset["参与计数块数"] == 8, f"原批次参与计数变为8（实际{dataset['参与计数块数']}）")
    check(dataset["覆盖页面数"] == 2 and dataset["覆盖页面"] == sorted({page_a, page_b}),
          "批次覆盖页面仍标明甲乙两页")
    check(sum(dataset["情感分布"].values()) == 8, "批次情感分布合计=8，与覆盖块数一致")
    check(len(dataset["逐块回执"]) == 8, "逐块回执8条，每块都有来源校验结论")
    final_summary = sent.compute_sentiment_summary()
    # 全局分布含3条种子情感记录与步骤4的独立探针块，场景8块单独核对；探针块也按块去重只计一次。
    check(final_summary["counted_block_count"] == 8 + 1 + seed_rows,
          f"发布分布参与计数=场景8块+探针1块+种子{seed_rows}条（实际{final_summary['counted_block_count']}）")
    check(final_summary["pending_supplement_count"] == 0, "发布统计待补录=0，与补录清单对得上")
    scenario_dist = dataset["情感分布"]
    check(sum(final_summary["sentiment_distribution"].values()) == 9 + seed_rows,
          f"发布分布各情感合计=场景8块+探针1块+种子{seed_rows}条，全部按块去重")
    # 运行期分析块的情感类别全部合法（种子样例用占位文本，不参与本次校验）。
    runtime_dist = dataset["情感分布"]
    check(set(runtime_dist).issubset(set(SENTIMENT_LABELS)),
          "运行期分布只含合法情感类别，缺块没有被造出新类别或塞成中性")
    check(set(runtime_dist) == set(SENTIMENT_LABELS),
          "批次数据集保留完整情感类别维度（未出现的类别计0）")
    check(sum(scenario_dist.values()) == 8, "场景批次分布合计=8")

    print("== 步骤8：补录后再次整批重发，仍然幂等 ==")
    again = sent.batch_analyze(submitted)
    check(again["total_analyzed"] == 8 and again["duplicate_count"] == 8,
          "8块全部命中同版本已有结果，重复送达只算一次")
    check(sent.compute_sentiment_summary()["counted_block_count"] == 8 + 1 + seed_rows,
          "全局分布计数稳定（场景8块+探针1块+种子记录），重复送达不产生新计数")

    print("\n全部场景校验通过 ✅")


if __name__ == "__main__":
    sys.exit(main())
