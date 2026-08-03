"""
会话管理器——定位/分割/归档。

职责：
1. 无感知 session 分割（时间/意图/预算三信号）
2. 获取或创建会话
3. 归档就绪会话
"""

import uuid
from dataclasses import dataclass


@dataclass
class Session:
    """会话"""

    session_id: str
    user_id: str
    status: str = "active"  # active | archived
    # TODO: 对接持久化（SQLite）


class SessionManager:
    """会话管理器。

    无感知分割 = 用户不需要手动结束/开启会话，
    系统通过三个信号自动切割：
    - 时间信号：空闲超过 N 分钟 → 新会话
    - 意图信号：从"测算"切到"闲聊"且上一轮已完成 → 可能新会话
    - 预算信号：token 预算耗尽 → 新会话
    """

    def __init__(self, ttl_idle_minutes: int = 30):
        self.ttl_idle_minutes = ttl_idle_minutes
        self._sessions: dict[str, Session] = {}

    async def get_or_create(
        self, session_id: str | None, user_id: str
    ) -> Session:
        """获取已有会话或创建新会话。

        Args:
            session_id: 请求传入的 session_id，None 则创建新会话
            user_id: 用户标识

        Returns:
            Session 对象
        """
        # 已有会话
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            # TODO: 检查 TTL，超时则自动归档 + 创建新会话
            return session

        # 创建新会话
        new_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        session = Session(session_id=new_id, user_id=user_id)
        self._sessions[new_id] = session
        return session

    async def archive(self, session_id: str) -> None:
        """归档会话"""
        session = self._sessions.get(session_id)
        if session:
            session.status = "archived"
            # TODO: 持久化到冷存储

    async def should_split(
        self, session_id: str, new_intent: str
    ) -> bool:
        """判断是否需要开启新会话（三信号检测）"""
        # TODO: 实现时间/意图/预算三信号
        return False
