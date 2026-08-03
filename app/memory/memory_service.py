"""
记忆服务——四层记忆系统。

L0: 用户画像（长期不变：星座、偏好）
L1: 长期事实（"用户最近在找工作"）
L2: 玄学记录（历史 readings：塔罗结果、排盘记录）
L3: 短期状态（当前对话窗口内的临时变量）

Recall: 同步操作，在请求上下文中完成。
Ingest:  异步操作，在回复返回后执行，不增加用户感知延迟。
"""

from dataclasses import dataclass, field


@dataclass
class MemoryLayer:
    """单层记忆的检索结果"""

    layer: str  # "L0" | "L1" | "L2" | "L3"
    items: list[dict] = field(default_factory=list)


class MemoryService:
    """四层记忆系统。

    面试话术：四层分层不是过度设计——L0/L1 长期稳定用结构化字段精确查询，
    L2 用向量检索找相似历史 reading 作为 in-context 参考，
    L3 就是当前窗口，无检索开销。每层存储和查询策略不同，
    强行合为一层才会出问题。
    """

    def __init__(self, db_path: str = "data/mysu.db"):
        self.db_path = db_path
        # TODO: 初始化 SQLite + sqlite-vec

    # ── Recall（同步）──────────────────────────────

    async def recall(self, session_id: str, user_id: str) -> list[MemoryLayer]:
        """同步查询所有四层记忆。

        Returns:
            按 L0→L3 排序的记忆层列表
        """
        # ── 占位实现 ──────────────────────────────
        return [
            MemoryLayer(layer="L0", items=[]),
            MemoryLayer(layer="L1", items=[]),
            MemoryLayer(layer="L2", items=[]),
            MemoryLayer(layer="L3", items=[{"role": "user", "content": "[L3 占位]"}]),
        ]

    async def recall_layer(
        self, session_id: str, user_id: str, layer: str
    ) -> MemoryLayer:
        """查询指定层记忆"""
        # TODO
        return MemoryLayer(layer=layer, items=[])

    # ── Ingest（异步）──────────────────────────────

    async def ingest(self, session_id: str, user_id: str, turn: dict) -> None:
        """异步入库一回合对话（user_message + assistant_reply + tool_results）。

        在 Generator 返回后调用，不阻塞用户。
        """
        # TODO: 解析 turn，更新 L1/L2/L3
        pass

    async def update_profile(self, user_id: str, profile: dict) -> None:
        """更新 L0 用户画像"""
        # TODO
        pass

    # ── 管理 ───────────────────────────────────────

    async def get_readings(
        self, user_id: str, limit: int = 20
    ) -> list[dict]:
        """获取用户的历史玄学记录（L2）"""
        # TODO
        return []

    async def archive_session(self, session_id: str) -> None:
        """归档会话到冷存储"""
        # TODO
        pass
