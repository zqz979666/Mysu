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
    clarify_params: dict = field(default_factory=dict)  # 用户在回答澄清时提取的参数
    abandon_clarify: bool = False  # true=用户转新话题，放弃当前澄清 pending


def _as_bool(value) -> bool:
    """LLM 布尔字段容错解析。

    小模型可能输出字符串 \"false\"/\"true\"——直接 bool(\"false\") 是 True，
    会把「回答澄清」误判成「放弃澄清」。按内容判定。
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "是")
    return bool(value)


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
        "clarify_params": {
            "type": "object",
            "description": "仅当用户在回答上一轮的澄清询问时填写：从用户消息中提取缺失参数的值（如 birth_date/sign/birth_time）。用户转新话题时不要填。",
        },
        "abandon_clarify": {
            "type": "boolean",
            "description": "仅当存在待补充信息时有效：true=用户没有回答澄清而是转到了新话题/闲聊，放弃当前澄清；false=用户在回答澄清。没有待补充信息时填 false。",
        },
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
- horoscope_daily: 每日星座运势。可选 sign（星座名），可选 birth_date + birth_time，可选 date（要查询的日期 YYYY-MM-DD，不填默认今天）

规则：
- tool_id 必须从可用工具列表中选择，不能凭空编造
- 如果用户消息明显对应某个工具（"看看我的星盘"→birth_chart、"今天运势如何"→horoscope_daily），正确判断 intent=execute
- 用户同时提供出生日期+想查星座 → 优先选 daily_transit 或 horoscope_daily（带 birth_date）
- 用户只问星座运势不提供出生日期 → 选 horoscope_daily（只传 sign）
- "我的运势/今天运势/星座运势/运势如何" → horoscope_daily，不要选 tarot_draw
- tarot_draw 只在用户明确要抽牌/占卜/塔罗时才选（如"抽张牌看看""塔罗占卜"）
- **date 时间参数**：用户消息里有时间表达（今天/明天/后天/下周/这周/周X/具体日期）时，为 horoscope_daily 或 daily_transit 填 date 参数，值为推算出的具体日期 YYYY-MM-DD（以"当前日期"为基准）："下周"→下周一，"明天"→明天，"这周"→本周一，"周X"→本周的周X。例如今天是 2026-08-05（周三），"查下周的运势"→ date="2026-08-10"
- **禁止编造参数值**：参数值只能来自用户消息原文（星座名、日期、数量等）。用户没提星座/日期 → 对应参数不填（系统会自动从画像注入或追问），**绝不填"用户提供的星座名""XX座""待补充"这类占位文字或描述性文字当参数值**——这是严重错误
- **主题类问题（财运/爱情/事业/健康/学业）可以多选工具组合**：
  - horoscope_daily 给出星象维度解读（如有 birth_date 则更精准）
  - tarot_draw 可抽牌针对该主题细问
  - 例如"我财运如何" → tool_selections 同时含 horoscope_daily 和 tarot_draw
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
        pending: dict | None = None,
    ) -> RouterDecision:
        """执行路由决策。

        Args:
            pending: 待澄清状态（上一轮询问用户在等什么参数）。
                     非空时 Router 需判断：用户是在回答澄清，还是转新话题。
        """
        # 1. ToolMatcher 候选召回（确定性，非 LLM）
        candidates = await self.matcher.match(user_message, intent_type="auto")

        # 2. 构造 prompt
        system = ROUTER_SYSTEM_PROMPT

        # 注入待澄清上下文（如有）
        if pending:
            tool_id = pending.get("tool_id", "")
            missing = pending.get("missing_params") or []
            partial = pending.get("partial_params") or {}
            system += (
                "\n\n## 待补充信息（上一轮系统询问了用户）\n"
                f"上一轮正在等待用户为工具 {tool_id} 补充参数：{'、'.join(missing)}\n"
                f"已收集到的参数：{partial or '无'}\n"
                "判断规则：\n"
                "- 如果用户消息**是在回答这个询问**（给出日期/时间/星座等）→ "
                "intent=execute，tool_selections 选择原工具，"
                "abandon_clarify=false，"
                "并在 clarify_params 中提取用户给出的参数值（如 birth_date='1995-06-15'）\n"
                "- 回答里的星座/日期**即使是别人的**（\"他是白羊座\"\"朋友生日是…\"）也要提取到 "
                "clarify_params——工具执行需要这些值；信息归属用户还是朋友由记忆系统判断，不归路由管\n"
                "- 如果用户消息**是新的请求/话题**（如换了个工具问、闲聊）→ "
                "abandon_clarify=true，忽略待补充信息，正常路由新意图，不要填 clarify_params\n"
                "- 用户既给了补充信息又提了新请求 → 优先回答新请求：abandon_clarify=true，不填 clarify_params\n"
                "- 拿不准时：只要用户消息里没有在补充缺失参数，就 abandon_clarify=true（宁可放弃澄清也不要困住用户）"
            )

        # 注入工具概要（含 display_name、description、schema）
        tool_summary = self.matcher.get_tool_summary(candidates)
        system += f"\n\n## 可用工具（只能从以下选择）\n{tool_summary}"

        # 注入当前日期——Router 推算"明天/下周/周X"等相对时间的基准。
        # 绝不依赖 LLM 心算日期（3B 模型算日期必错），基准日由系统给出。
        from datetime import date
        _weekday_cn = "一二三四五六日"[date.today().weekday()]
        system += (
            f"\n\n## 当前日期\n"
            f"今天是 {date.today().isoformat()} 星期{_weekday_cn}。"
            f"推算'明天/后天/下周/这周/周X'等相对时间时以此为基准，"
            f"date 参数直接填 YYYY-MM-DD 具体日期。"
        )

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
        """解析 LLM 结构化输出 → RouterDecision（防御性：容忍小模型返回脏格式）"""
        if not isinstance(raw, dict):
            return RouterDecision(intent="direct", reasoning="结构化输出格式异常")

        intent = raw.get("intent", "direct")

        tool_selections = []
        raw_ts = raw.get("tool_selections") or []
        # 小模型可能返回多种形态：
        #   标准: [{"tool_id": "x", "params": {...}}]
        #   字符串数组: ["birth_chart"]
        #   dict 值形态: {"tool1": "horoscope_daily"}（key=编号, value=tool_id）
        #   dict 键形态: {"tarot_draw": {"count": 3}}（key=tool_id, value=params）
        if isinstance(raw_ts, dict):
            # 占位键：小模型可能输出 {"tool": "horoscope_daily", "params": {...}}
            # 或 {"tool1": "tarot_draw"}（key 是占位词，不是 tool_id）
            placeholder_keys = {
                "tool", "tools", "tool1", "tool2", "tool3", "tool4",
                "params", "parameters", "selection", "selections", "item", "item1",
            }
            last_tid: str | None = None
            for k, v in raw_ts.items():
                if isinstance(v, str):
                    # 值形态：{"tool1": "horoscope_daily"} → tool_id 是 value
                    last_tid = v
                    tool_selections.append(ToolSelection(tool_id=v, params={}))
                elif isinstance(v, dict):
                    tid = v.get("tool_id")
                    if tid:
                        # 嵌套标准形态：{"a": {"tool_id": "x", "params": {...}}}
                        last_tid = tid
                        tool_selections.append(ToolSelection(
                            tool_id=tid,
                            params=v.get("params") or v.get("parameters") or {},
                        ))
                    elif k in ("params", "parameters") and last_tid and tool_selections:
                        # 参数键 + 上一个工具 → 合并（真实事故：qwen 输出
                        # {"tool": "horoscope_daily", "params": {"sign": "白羊座"}}，
                        # 之前把 "params" 当 tool_id 导致参数全丢 → 澄清死循环）
                        merged = {**tool_selections[-1].params, **v}
                        tool_selections[-1] = ToolSelection(
                            tool_id=last_tid, params=merged
                        )
                    else:
                        # 键形态：{"tarot_draw": {"count": 3}}（key=tool_id）
                        # 或占位键无 tool_id（无法恢复，跳过 tool_id）
                        real_tid = None if k in placeholder_keys else k
                        last_tid = real_tid or last_tid
                        tool_selections.append(
                            ToolSelection(tool_id=real_tid or "", params=v)
                        )
                else:
                    tool_selections.append(
                        ToolSelection(tool_id=k, params={})
                    )
        else:
            for ts in raw_ts:
                # 字符串数组 ["birth_chart"]
                if isinstance(ts, str):
                    tool_selections.append(
                        ToolSelection(tool_id=ts, params={})
                    )
                elif isinstance(ts, dict):
                    tool_selections.append(
                        ToolSelection(
                            tool_id=ts.get("tool_id", ""),
                            # 兼容 qwen 输出的 "parameters" 键（真实事故：
                            # 模型用错键名导致参数全丢 → 澄清死循环）
                            params=ts.get("params") or ts.get("parameters") or {},
                        )
                    )
                # 其他类型忽略

        return RouterDecision(
            intent=intent,
            reasoning=raw.get("reasoning", ""),
            tool_selections=tool_selections,
            response_direct=raw.get("response_direct", ""),
            knowledge_query=raw.get("knowledge_query", ""),
            trace_lookup_index=raw.get("trace_lookup_index"),
            clarify_params=raw.get("clarify_params") or {},
            abandon_clarify=_as_bool(raw.get("abandon_clarify", False)),
        )
