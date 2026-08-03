"""
请求数据模型
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求。session_id 为空时 SessionManager 自动创建新会话。"""

    message: str = Field(..., description="用户输入文本")
    session_id: str | None = Field(
        default=None, description="会话 ID，空则创建新会话"
    )


class EventsPendingRequest(BaseModel):
    """拉取待推送事件。客户端轮询用。"""

    session_id: str = Field(..., description="会话 ID")
    mark_id: str | None = Field(
        default=None, description="上次已处理的最大事件 ID，只返回更新的"
    )
