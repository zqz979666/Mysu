"""
上下文组装器——将工具执行结果、知识检索结果、记忆注入组装成 Generator 的 prompt。

关键职责：token 预算控制。
不是简单的字符串拼接——要在有限的 token 窗口内做优先级截断。
裁剪顺序：tool_output > knowledge_hits > l2_readings > l1_facts > profile
"""

from dataclasses import dataclass, field
from app.models.domain import ToolResult
from app.knowledge.knowledge_retriever import KnowledgeHit
from app.agent.context_loader import LoadedContext


@dataclass
class GeneratorContext:
    """Generator 的完整输入上下文"""

    user_message: str
    system_prompt_fragment: str       # 画像/记忆/长期事实
    tool_outputs: str                 # 工具执行结果的文本化
    knowledge_fragments: str          # 知识检索结果
    max_tokens: int = 4096            # 预算上限（留给 generator 的空间）


class ContextBuilder:
    """上下文组装器——在 token 预算约束下拼装 Generator 的输入。

    面试话术：为什么需要 ContextBuilder？因为 token 预算是硬约束——
    你不能把全量工具输出 + 全量知识片段 + 全量记忆无脑塞给 LLM。
    需要按优先级截断：工具输出 > 知识片段 > 历史 readings > 长期事实 > 画像。
    裁剪逻辑是确定性的（规则），不是 LLM 做的。
    """

    def __init__(self, max_total_tokens: int = 4096):
        self.max_total_tokens = max_total_tokens

    def build(
        self,
        user_message: str,
        context: LoadedContext,
        tool_results: list[ToolResult],
        knowledge_hits: list[KnowledgeHit] | None = None,
    ) -> GeneratorContext:
        """组装 Generator 上下文。

        Args:
            user_message: 用户原始消息
            context: 四层记忆上下文
            tool_results: 工具执行结果
            knowledge_hits: 知识检索结果（KNOWLEDGE/EXPLAIN 意图时）

        Returns:
            GeneratorContext——可直接喂给 Generator 的 prompt 组装结果
        """
        # 1. 工具输出的文本化
        tool_outputs = self._format_tool_results(tool_results)

        # 2. 知识片段的文本化
        knowledge = ""
        if knowledge_hits:
            knowledge = self._format_knowledge_hits(knowledge_hits)

        # 3. 上下文片段
        profile_fragment = ""
        if hasattr(context, 'to_system_prompt_fragment'):
            profile_fragment = context.to_system_prompt_fragment()

        # 4. Token 预算控制（TODO: 实现真实 tokenizer 计数 + 裁剪）
        # 当前用字符数近似
        system = profile_fragment
        available = self.max_total_tokens - self._estimate_tokens(user_message)

        # 优先级：tool_output > knowledge > profile
        # 简化裁剪：如果超预算，优先保留 tool_output
        # TODO: 实现基于 tiktoken 的精确实时裁剪
        if self._estimate_tokens(tool_outputs) > available * 0.5:
            tool_outputs = tool_outputs[: int(available * 0.5 * 4)] + "\n...(截断)"

        return GeneratorContext(
            user_message=user_message,
            system_prompt_fragment=system,
            tool_outputs=tool_outputs,
            knowledge_fragments=knowledge,
        )

    def _format_tool_results(self, results: list[ToolResult]) -> str:
        """将工具结果列表 → 文本片段"""
        if not results:
            return "[本回合未调用工具]"

        lines = ["## 工具执行结果"]
        for i, r in enumerate(results, 1):
            if r.success:
                output_str = str(r.output) if r.output else "成功（无输出）"
                lines.append(f"{i}. ✓ {r.tool_id}: {output_str}")
            else:
                lines.append(f"{i}. ✗ {r.tool_id}: {r.error}")
            if r.trace:
                lines.append(f"   执行记录: {r.trace}")
        return "\n".join(lines)

    def _format_knowledge_hits(self, hits: list[KnowledgeHit]) -> str:
        """将知识检索结果 → 文本片段"""
        if not hits:
            return ""

        lines = ["## 相关知识"]
        for hit in hits[:5]:
            lines.append(f"- [{hit.source}] {hit.content[:200]}")
        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数（4 字符 ≈ 1 token）"""
        # TODO: 替换为 tiktoken 精确计数
        return len(text) // 4
