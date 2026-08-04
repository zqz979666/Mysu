"""
Router——LLM 决策点①：类型判定 + 工具选择 + 参数填充。

这是整个 runtime 两个同步 LLM 调用点中的第一个。
合并为一次结构化输出：「先想大类（意图类型）→ 再想具体（从候选选工具+填参）」。
分步思考不是雇佣员工——一次 LLM 调用完成，没有循环。

输出：
{
  "intent": "execute" | "knowledge" | "explain" | "direct",
  "reasoning": "...",
  "tool_selections": [
    {"tool_id": "tarot_draw", "params": {"count": 3}},
    ...
  ],
  "response_direct": "..."  // 仅 direct 意图有值
}
"""

from dataclasses import dataclass, field
from app.llm.llm_client import LLMClient, LLMCallConfig
from app.agent.tool_matcher import ToolMatcher
from app.agent.context_loader import LoadedContext


@dataclass
class ToolSelection:
    """Router 选择一个工具的结果"""

    tool_id: str
    params: dict = field(default_factory=dict)


@dataclass
class RouterDecision:
    """Router 的完整决策结果"""

    intent: str                      # execute | knowledge | explain | direct
    reasoning: str = ""
    tool_selections: list[ToolSelection] = field(default_factory=list)
    response_direct: str = ""        # direct 意图的直接回复
    knowledge_query: str = ""        # knowledge 意图的检索 query
    trace_lookup_index: int | None = None  # explain 意图：查第几次调用


ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["execute", "knowledge", "explain", "direct"],
        },
        "reasoning": {"type": "string"},
        "tool_selections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["tool_id", "params"],
            },
        },
        "response_direct": {"type": "string"},
        "knowledge_query": {"type": "string"},
        "trace_lookup_index": {"type": "integer"},
    },
    "required": ["intent"],
}

ROUTER_SYSTEM_PROMPT = """你是 Mysu 的意图路由器。你只做一件事：判断用户想做什么，选哪个工具。

意图类型：
- execute: 执行测算（塔罗抽牌、本命星盘、流年星象、星座运势）——选工具+填参数
- knowledge: 问知识/原理（"塔罗的原理是什么？""什么是上升星座？"）——返回检索 query
- explain: 质疑/追问上次结果（"为什么是这个结果？"）——返回查哪次调用的 trace
- direct: 闲聊/问候/与功能无关 → 直接回复（无需填 tool_selections）

工具列表与参数：
- tarot_draw: 塔罗抽牌。需要 count (1 或 3)，可选 question（用户想问的问题）
- birth_chart: 本命星盘。需要 birth_date (YYYY-MM-DD)，可选 birth_time (HH:MM，默认12:00)
- daily_transit: 流年星象。需要 birth_date，可选 birth_time 和 date（要查询的日期）
- horoscope_daily: 每日星座运势。可选 sign（星座名），可选 birth_date + birth_time

规则：
- tool_id 必须从可用工具列表中选择，不能凭空编造
- 如果用户消息明显对应某个工具（"看看我的星盘"→birth_chart、"今天运势如何"→horoscope_daily），正确判断 intent=execute
- 用户同时提供出生日期+想查星座 → 优先选 daily_transit 或 horoscope_daily（带 birth_date）
- 用户只问星座运势不提供出生日期 → 选 horoscope_daily（只传 sign）
- 如果候选列表为空且意图是 execute，降级为 direct 告知用户"该功能暂不可用"
- 如果意图是 direct，response_direct 必须包含友好的回复内容"""


class Router:
    """意图路由——LLM 决策点①。"""

    def __init__(self, llm_client: LLMClient, tool_matcher: ToolMatcher):
        self.llm = llm_client
        self.matcher = tool_matcher
        self.last_tokens_in: int = 0
        self.last_tokens_out: int = 0

    async def route(
        self,
        user_message: str,
        context: LoadedContext,
        request_id: str = "",
        session_id: str = "",
    ) -> RouterDecision:
        """执行路由决策。"""
        # 1. ToolMatcher 候选召回（确定性，非 LLM）
        candidates = await self.matcher.match(user_message, intent_type="auto")

        # 2. 构造 prompt
        system = ROUTER_SYSTEM_PROMPT

        # 注入工具概要（含 display_name、description、schema）
        tool_summary = self.matcher.get_tool_summary(candidates)
        system += f"\n\n## 可用工具（只能从以下选择）\n{tool_summary}"

        if context:
            fragment = (
                context.to_system_prompt_fragment()
                if hasattr(context, 'to_system_prompt_fragment')
                else ""
            )
            if fragment:
                system += f"\n\n## 用户上下文\n{fragment}"

        user_prompt = (
            f"用户消息：「{user_message}」\n\n"
            f"请输出结构化 JSON 路由决策。"
        )

        # 3. LLM 调用（合并为一次结构化输出）
        result = await self.llm.call(
            LLMCallConfig(
                system_prompt=system,
                user_prompt=user_prompt,
                response_format=ROUTER_SCHEMA,
                call_type="router",
                request_id=request_id,
                session_id=session_id,
            )
        )

        self.last_tokens_in = result.tokens_in
        self.last_tokens_out = result.tokens_out

        # 4. 解析结构化输出
        decision = self._parse_decision(result.structured_output or {})
        return decision

    def _parse_decision(self, raw: dict) -> RouterDecision:
        """解析 LLM 结构化输出 → RouterDecision"""
        intent = raw.get("intent", "direct")

        tool_selections = []
        for ts in raw.get("tool_selections", []) or []:
            tool_selections.append(
                ToolSelection(
                    tool_id=ts.get("tool_id", ""),
                    params=ts.get("params", {}),
                )
            )

        return RouterDecision(
            intent=intent,
            reasoning=raw.get("reasoning", ""),
            tool_selections=tool_selections,
            response_direct=raw.get("response_direct", ""),
            knowledge_query=raw.get("knowledge_query", ""),
            trace_lookup_index=raw.get("trace_lookup_index"),
        )
