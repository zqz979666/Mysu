"""
上下文加载器——加载画像 + 摘要 + 记忆 + 历史工具结果。

在 Router 调用前执行，组装注入 LLM system_prompt 的上下文。
"""

from dataclasses import dataclass, field
from app.memory.memory_service import MemoryService, MemoryLayer


@dataclass
class LoadedContext:
    """Router/Generator 注入的上下文"""

    user_profile: dict = field(default_factory=dict)      # L0
    long_term_facts: list[dict] = field(default_factory=list)  # L1
    recent_readings: list[dict] = field(default_factory=list)  # L2
    short_term_state: list[dict] = field(default_factory=list)  # L3
    previous_results: list[dict] = field(default_factory=list)


class ContextLoader:
    """上下文加载器。

    从 MemoryService 拉四层记忆 + 会话内历史工具结果 →
    组装成 LoadedContext，供 Router 和 Generator 的 system_prompt 使用。
    """

    def __init__(self, memory_service: MemoryService):
        self.memory = memory_service

    async def load(
        self, session_id: str, user_id: str
    ) -> LoadedContext:
        """加载全部上下文。

        TODO: 当前占位实现，需对接 MemoryService 的真实查询。
        """
        layers = await self.memory.recall(session_id, user_id)

        ctx = LoadedContext()
        for layer in layers:
            match layer.layer:
                case "L0":
                    ctx.user_profile = layer.items[0] if layer.items else {}
                case "L1":
                    ctx.long_term_facts = layer.items
                case "L2":
                    ctx.recent_readings = layer.items
                case "L3":
                    ctx.short_term_state = layer.items

        return ctx

    def to_system_prompt_fragment(self, ctx: LoadedContext) -> str:
        """将 LoadedContext 转换为 system_prompt 注入片段。

        面试话术：ContextBuilder 负责拼装 + token 预算控制，
        这里只是数据→文本的转换，不涉及截断逻辑。
        """
        parts: list[str] = []

        if ctx.user_profile:
            profile_str = ", ".join(
                f"{k}={v}" for k, v in ctx.user_profile.items()
            )
            parts.append(f"[用户画像] {profile_str}")

        if ctx.long_term_facts:
            facts_str = "; ".join(
                f.get("content", "") for f in ctx.long_term_facts
            )
            parts.append(f"[长期事实] {facts_str}")

        if ctx.recent_readings:
            parts.append(f"[近期测算记录] {len(ctx.recent_readings)} 条")

        return "\n".join(parts)
