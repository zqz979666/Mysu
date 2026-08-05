"""
工具匹配器——确定性候选召回（非 LLM）。

这是给 LLM 缩小选择空间的前置过滤器，和天池的 FieldMatcher 一模一样。
不是子 agent——没有 LLM 循环，没有独立上下文，就是一个确定性检索函数。

策略：
1. 精确匹配：tool_id 或 display_name 精确命中
2. 同义词匹配：预定义的别名映射（"抽一张" → 塔罗抽牌）
3. 关键词匹配：如果用户消息包含关键词则召回对应工具

将来策略升级：
4. 向量匹配：embedding 余弦相似度召回 top-k（主力）

面试话术：ToolMatcher 是确定性函数（规则 + 未来 embedding 检索），
不是 agent 层。LLM 只做一次「从候选里选」的决策，
没有循环、没有独立上下文——所以不是子 agent。
"""

import re

from app.models.domain import ToolSpec
from app.observability.logger import logger


class ToolMatcher:
    """确定性工具候选召回。

    输入：用户原始消息
    输出：候选 tool_id 列表（LLM 只能从这个候选集里选）
    """

    def __init__(self, top_k: int = 10):
        self.top_k = top_k
        # 同义词映射: alias → tool_id 或 [tool_id, ...]（多值用于主题词）
        self._aliases: dict[str, str | list[str]] = {}
        # 所有已注册的工具
        self._all_tools: list[ToolSpec] = []

    def add_alias(self, alias: str, tool_id: str) -> None:
        """注册单个同义词"""
        self._aliases[alias] = tool_id

    def add_aliases(self, mapping: dict[str, str | list[str]]) -> None:
        """批量注册同义词（值可以是单个 tool_id 或列表）"""
        self._aliases.update(mapping)

    async def rebuild_index(self, tools: list[ToolSpec]) -> None:
        """重建工具索引（领域包注册/注销时调用）。

        当前用内存列表 + 关键词匹配。
        TODO: 集成 sqlite-vec 做向量相似度召回。
        """
        self._all_tools = list(tools)
        logger.info(f"ToolMatcher 索引已重建: {len(tools)} 个工具")

    async def match(
        self, user_message: str, intent_type: str = "auto"
    ) -> list[str]:
        """召回的候选 tool_id 列表。

        Args:
            user_message: 用户原始消息
            intent_type: Router 判定的意图类型（当前仅用于日志，后续可用于限定领域）

        Returns:
            候选 tool_id 列表（按相关性排序，最多 top_k 个）
        """
        msg = user_message.strip()
        candidates: list[str] = []

        # ── 1. 精确匹配 ──────────────────────────
        for tool in self._all_tools:
            if tool.tool_id in msg or tool.display_name in msg:
                if tool.tool_id not in candidates:
                    candidates.append(tool.tool_id)

        # ── 2. 同义词匹配（值可为单个 tool_id 或列表）──
        for alias, value in self._aliases.items():
            if alias not in msg:
                continue
            if isinstance(value, list):
                for tid in value:
                    if tid not in candidates:
                        candidates.append(tid)
            else:
                if value not in candidates:
                    candidates.append(value)

        # ── 3. 关键词匹配 ─────────────────────────
        # 工具 description 中的关键词命中
        for tool in self._all_tools:
            if tool.tool_id in candidates:
                continue
            keywords = tool.description.split("、")
            for kw in keywords:
                if len(kw) >= 2 and kw in msg:
                    candidates.append(tool.tool_id)
                    break

        # ── 如果没有命中，返回全部工具（让 LLM 自己选） ──
        if not candidates and len(self._all_tools) <= self.top_k:
            candidates = [t.tool_id for t in self._all_tools]

        # ── 截断到 top_k ──
        return candidates[:self.top_k] if len(candidates) > self.top_k else candidates

    # ── 辅助：获取 tool_id → display_name 映射 ──

    def get_tool_summary(self, tool_ids: list[str]) -> str:
        """生成候选工具的摘要文本（注入 Router prompt）"""
        lines = []
        for tid in tool_ids:
            for tool in self._all_tools:
                if tool.tool_id == tid:
                    lines.append(f"- {tool.tool_id}: {tool.display_name} — {tool.description}")
                    break
        return "\n".join(lines) if lines else "[无可用工具]"
