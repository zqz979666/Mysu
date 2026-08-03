"""
响应数据模型
"""

from datetime import datetime
from pydantic import BaseModel, Field


class ChatResponse(BaseModel):
    """对话响应"""

    session_id: str = Field(..., description="会话 ID")
    reply: str = Field(..., description="助手回复文本")
    intent: str = Field(..., description="Router 判定的意图类型")
    tool_calls: list[str] | None = Field(
        default=None, description="本次调用的工具 ID 列表（调试用）"
    )


class PendingEvent(BaseModel):
    """推送事件"""

    event_id: str
    event_type: str  # "push_message" | "state_change" | ...
    payload: dict
    created_at: datetime


class EventsPendingResponse(BaseModel):
    """待推送事件响应"""

    events: list[PendingEvent] = Field(default_factory=list)
    latest_event_id: str | None = Field(default=None)


class ErrorResponse(BaseModel):
    """错误响应"""

    error: str
    detail: str | None = None
