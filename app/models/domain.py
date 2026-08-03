"""
领域模型：DomainPack / Skill / ToolSpec / ExecutionContext

核心理念：
- DomainPack 是可插拔的领域能力包（玄学、天气、...）
- Skill 是领域内的功能分组（塔罗、排盘、黄历）
- ToolSpec 是具体的执行单元（抽牌、排八字、查吉日）
- ToolSpec.execute 允许任意实现——纯函数或内部带 LLM 循环的子 agent
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


# ── Intent 类型 ──────────────────────────────────────────────


class IntentType(StrEnum):
    """Router 判定的意图大类。

    面试话术：这是「决策链的第一步拆解」——先想大类缩小范围，
    和「子 agent」没有关系。子 agent 的特征是独立上下文+自主循环。
    """

    EXECUTE = "execute"       # 执行领域工具（塔罗抽牌、排盘）
    KNOWLEDGE = "knowledge"   # 知识检索（元问题："塔罗的原理是什么？"）
    EXPLAIN = "explain"       # 解释上次测算结果（需要 engine trace）
    DIRECT = "direct"         # 直接对话（闲聊、问候）


# ── ToolSpec ─────────────────────────────────────────────────


class ToolSpec(ABC):
    """工具规格——可执行的最小单元。

    关键设计：execute() 允许任意实现。
    - 现在：纯函数（塔罗 RNG、八字排盘）——零 LLM
    - 将来：内部带 LLM 循环的子图（如"分析半年运势规律"）
            这才会变成真正的子 agent，但由领域包自己决定，框架无感。
    """

    def __init__(self, tool_id: str, display_name: str, description: str, schema: dict):
        self.tool_id = tool_id
        self.display_name = display_name
        self.description = description
        self.schema = schema  # JSON Schema 形式的参数定义

    @abstractmethod
    async def execute(self, params: dict, ctx: "ExecutionContext") -> "ToolResult":
        """执行工具。可以是纯函数或异步子 agent。"""
        ...

    def to_embedding_text(self) -> str:
        """生成用于向量检索的文本（ToolMatcher 用）"""
        return f"{self.display_name} {self.description}"


# ── Skill ────────────────────────────────────────────────────


@dataclass
class Skill:
    """一个领域内的一组相关工具"""

    skill_id: str
    display_name: str
    description: str
    tools: list[ToolSpec] = field(default_factory=list)

    def add_tool(self, tool: ToolSpec) -> None:
        self.tools.append(tool)


# ── DomainPack ───────────────────────────────────────────────


class DomainPack(ABC):
    """可插拔的领域能力包。

    设计原则：拿走玄学包注入另一个领域包，即成通用 agent——
    路由/记忆/生成全部复用，只是领域能力换了一组。
    """

    def __init__(self, domain_id: str, display_name: str, description: str):
        self.domain_id = domain_id
        self.display_name = display_name
        self.description = description
        self.skills: dict[str, Skill] = {}

    async def on_load(self) -> None:
        """领域包加载钩子：初始化向量索引、预热资源等"""
        pass

    async def on_unload(self) -> None:
        """领域包卸载钩子"""
        pass

    def get_all_tools(self) -> list[ToolSpec]:
        """获取该领域包下所有工具（扁平化）"""
        tools: list[ToolSpec] = []
        for skill in self.skills.values():
            tools.extend(skill.tools)
        return tools

    def get_tool(self, tool_id: str) -> ToolSpec | None:
        """按 tool_id 查找工具"""
        for skill in self.skills.values():
            for tool in skill.tools:
                if tool.tool_id == tool_id:
                    return tool
        return None

    def add_skill(self, skill: Skill) -> None:
        self.skills[skill.skill_id] = skill


# ── 上下文 ───────────────────────────────────────────────────


@dataclass
class ToolResult:
    """工具执行结果"""

    tool_id: str
    success: bool
    output: dict | None = None      # 成功时的结构化输出
    error: str | None = None        # 失败时的错误信息
    trace: str | None = None        # 执行 trace，用于元问题解释（"这结果怎么出来的？"）


@dataclass
class ExecutionContext:
    """工具执行上下文——贯穿整个请求生命周期的不可变上下文"""

    session_id: str
    user_id: str
    request_id: str
    # 从上下文加载层注入
    user_profile: dict | None = None
    session_summary: list[dict] | None = None
    memory_items: list[dict] | None = None
    previous_results: list[ToolResult] | None = None
