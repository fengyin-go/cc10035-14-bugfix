"""HTTP 接口层验证：通过真实 FastAPI 路由演练缺块补录全流程。

使用标准库 urllib，不引入额外依赖；与服务层集成测试覆盖不同层级。
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8017"


def call(module: str, action: str, *, args=None, kwargs=None) -> dict:
    body = json.dumps({"args": args or [], "kwargs": kwargs or {}}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/domain/{module}/actions/{action}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok", True):
        raise AssertionError(f"领域动作失败：{payload.get('message')}")
    return payload["data"]


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


def main() -> None:
    import time

    print("== HTTP：切分两页 ==")
    page_a, page_b = f"http-甲页-{time.time_ns()}", f"http-乙页-{time.time_ns()}"
    blocks_a = call("text_segment", "segment_page", args=[page_a])["blocks"]
    blocks_b = call("text_segment", "segment_page", args=[page_b])["blocks"]
    # 乙页只读取了3块，最后一块从未入库：用唯一虚构ID模拟未读取的缺块。
    missing_id = f"missing-{time.time_ns()}"
    ids = [b["块ID"] for b in blocks_a + blocks_b[:-1]] + [missing_id]

    print("== HTTP：同批提交8块、乙页缺1块 ==")
    batch = call("sentiment_tag", "batch_analyze",
                 kwargs={"text_block_ids": ids, "text_versions": {missing_id: "v-missing"}})
    check(batch["ok"], "批量分析接口返回 ok")
    check(batch["missing_count"] == 1, f"缺块1条（实际{batch['missing_count']}）")
    check(batch["total_analyzed"] == 7, "已分析7块")
    check(len(batch["covered_pages"]) == 2, "标明覆盖2个页面")
    check(sum(batch["sentiment_distribution"].values()) == 7, "分布合计7，缺块不计中性")
    batch_id = batch["批次ID"]

    print("== HTTP：补录清单查询 ==")
    pending = call("text_segment", "list_supplements", kwargs={"status": "待补录"})
    check(len(pending) >= 1 and any(s["块ID"] == missing_id for s in pending),
          "补录清单接口可查到乙页缺块")
    sup_id = next(s["补录ID"] for s in pending if s["块ID"] == missing_id)

    print("== HTTP：情感分布摘要与负向复查入口 ==")
    summary = call("sentiment_tag", "compute_sentiment_summary")
    check(summary["pending_supplement_blocks"] and missing_id in summary["pending_supplement_blocks"],
          "发布分布标明待补录块")
    check(summary["covered_page_count"] >= 2, "发布分布标明实际覆盖页面数")
    negatives = call("sentiment_tag", "negative_blocks_for_review",
                     kwargs={"batch_id": batch_id})
    check(isinstance(negatives, list) and all(n["block_id"] != missing_id for n in negatives),
          "负向复查入口不含待补录缺块")

    print("== HTTP：重试幂等 ==")
    retry = call("sentiment_tag", "batch_analyze",
                 kwargs={"text_block_ids": ids, "text_versions": {missing_id: "v-missing"}})
    check(retry["duplicate_count"] == 7 and retry["total_analyzed"] == 7,
          "重复送达7块全部识别为重复，计数不增加")

    print("== HTTP：工作台补回原标识并重投 ==")
    restored = call("text_segment", "restore_missing_block",
                    kwargs={"supplement_id": sup_id, "source_page": page_b, "block_type": "list_item"})
    check(restored["ok"] and restored["block"]["块ID"] == missing_id, "缺块按原标识补回")
    redeliver = call("sentiment_tag", "redeliver_supplement",
                     kwargs={"supplement_id": sup_id})
    check(redeliver["ok"], "引用原批次重投成功")

    print("== HTTP：补录后对账 ==")
    dataset = call("sentiment_tag", "get_batch", kwargs={"batch_id": batch_id})
    check(dataset["参与计数块数"] == 8 and dataset["待补录块数"] == 0,
          "原批次数据集补录后覆盖8块、待补录清零")
    check(dataset["delivered"] and len(dataset["逐块回执"]) == 8, "完整交付且逐块回执齐全")
    pending_after = call("text_segment", "list_supplements", kwargs={"status": "待补录"})
    check(not any(s["块ID"] == missing_id for s in pending_after), "补录清单不再含该缺块")

    print("\nHTTP 接口层场景校验通过 ✅")


if __name__ == "__main__":
    sys.exit(main())
