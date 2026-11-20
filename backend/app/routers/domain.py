"""领域动作接口：模块特有的跨表业务动作（批量分析、补录、重投、分布查询）。

通用资源路由只承载列表/登记/状态流转；跨模块协作的领域动作集中在这里，
按 module + action 分派到各领域服务，路由层不做业务判断。
"""
from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.sentiment_tag import SentimentTagService
from app.services.text_segment import TextSegmentService

router = APIRouter(prefix="/api/domain", tags=["领域动作"])


class DomainPayload(BaseModel):
    # 位置参数按声明顺序传入（如批量分析的块ID列表）；其余作为关键字参数。
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


# 每个模块允许的领域动作 → 处理方法名。
DOMAIN_ACTIONS: dict[str, dict[str, str]] = {
    "text_segment": {
        "segment_page": "segment_page",
        "feed_sentiment_tag": "feed_sentiment_tag",
        "list_supplements": "list_supplements",
        "restore_missing_block": "restore_missing_block",
    },
    "sentiment_tag": {
        "batch_analyze": "batch_analyze",
        "redeliver_supplement": "redeliver_supplement",
        "list_batches": "list_batches",
        "get_batch": "get_batch",
        "negative_blocks_for_review": "negative_blocks_for_review",
        "compute_sentiment_summary": "compute_sentiment_summary",
    },
}

_SERVICE_FACTORIES = {
    "text_segment": TextSegmentService,
    "sentiment_tag": SentimentTagService,
}


@router.post("/{module}/actions/{action}")
def run_domain_action(module: str, action: str, body: DomainPayload) -> dict[str, Any]:
    allowed = DOMAIN_ACTIONS.get(module)
    if allowed is None or action not in allowed:
        raise HTTPException(
            status_code=404,
            detail=f"模块 {module} 不支持领域动作 {action}",
        )
    service = _SERVICE_FACTORIES[module]()
    method = getattr(service, allowed[action])
    # 只透传方法签名中存在的关键字参数，避免前端多传字段触发 TypeError。
    sig = inspect.signature(method)
    kwargs = {
        key: value for key, value in body.kwargs.items()
        if key in sig.parameters
    }
    data = method(*body.args, **kwargs)
    if isinstance(data, dict) and data.get("ok") is False:
        # 业务失败（如缺块仍未补回）：保留失败消息，不包装成成功响应。
        return {"ok": False, "data": data, "message": data.get("message", "领域动作执行失败")}
    return {"ok": True, "data": data}
