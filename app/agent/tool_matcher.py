"""
工具匹配器——确定性候选召回（非 LLM）。

这是给 LLM 缩小选择空间的前置过滤器，和天池的 FieldMatcher 一模一样。
不是子 agent——没有 LLM 循环，没有独立上下文，就是一个确定性检索函数。

策略：
1. 精确匹配：tool_id 或 display_name 精确命中
2. 同义词匹配：预定义的别名映射（"抽一张" → 塔罗抽牌）
3. 向量匹配：embedding 余弦相似度召回 top-k（主力）
"""

from app.models.domain import ToolSpec


class ToolMatcher:
    """确定性工具候选召回。

    输入：用户原始消息 + 已判定的意图类型
    输出：候选 tool_id 列表（LLM 只能从这个候选集里选）

    面试话术：ToolMatcher 是确定性函数（embedding 检索），
    不是 agent 层。LLM 只做一次「从候选里选」的决策，
    没有循环、没有独立上下文——所以不是子 agent。
    """

    def __init__(self, top_k: int = 10):
        self.top_k = top_k
        # 同义词映射
        self._aliases: dict[str, str] = {}
        # TODO: 对接向量存储（ChromaDB / sqlite-vec）
        # TODO: 初始化时从 DomainRegistry 拉全量工具建向量索引

    async def match(
        self, user_message: str, intent_type: str
    ) -> list[str]:
        """召回的候选 tool_id 列表。

        Args:
            user_message: 用户原始消息
            intent_type: Router 判定的意图类型（用于限定领域）

        Returns:
            候选 tool_id 列表（按相关性排序）

        TODO: 实现三步匹配（精确→同义词→向量），当前占位返回空。
        """
        # ── 占位实现 ──────────────────────────────
        # 1. 精确匹配
        # 2. 同义词匹配
        # 3. 向量匹配
        return []

    def add_alias(self, alias: str, tool_id: str) -> None:
        """注册同义词（"抽一张" → "tarot_draw"）"""
        self._aliases[alias] = tool_id

    async def rebuild_index(self, tools: list[ToolSpec]) -> None:
        """重建向量索引（领域包注册/注销时调用）"""
        # TODO: 对所有 ToolSpec.to_embedding_text() 建向量索引
        pass
