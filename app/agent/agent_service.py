"""
AgentService——主编排器（纯函数流水线 + 全链路日志 + 记忆落表 + 澄清闸门）

请求生命周期：
入口 → 澄清检查 → SessionManager → ContextLoader → Router（LLM①）
     → ValidationGate → 画像注入 → 参数检查（缺参→澄清）→ ToolExecutor
     → 画像回写 → ContextBuilder → Generator（LLM②）→ 返回 → 异步 Ingest

面试核心主张：
  整个 runtime 只有两个同步 LLM 调用点（Router + Generator）。
  澄清是确定性的参数完备性检查，不消耗 LLM 调用。
"""

import time
import asyncio
import re

from app.models.domain import ExecutionContext
from app.models.requests import ChatRequest
from app.models.responses import ChatResponse

from app.agent.session_manager import SessionManager
from app.agent.context_loader import ContextLoader
from app.agent.router import Router
from app.agent.validation_gate import ValidationGate
from app.agent.tool_executor import ToolExecutor
from app.agent.context_builder import ContextBuilder
from app.agent.generator import Generator

from app.llm.llm_client import LLMClient
from app.agent.tool_matcher import ToolMatcher
from app.memory.memory_service import MemoryService
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.domain.domain_registry import DomainRegistry
from app.observability.logger import logger
from app.observability.request_logger import RequestLogger
from app.observability.metrics import Metrics


class AgentService:
    """主编排器——每步全链路日志透明。"""

    def __init__(
        self,
        llm_client: LLMClient,
        domain_registry: DomainRegistry,
        memory_service: MemoryService,
        knowledge_retriever: KnowledgeRetriever,
        metrics: Metrics | None = None,
    ):
        self.llm = llm_client
        self.registry = domain_registry
        self.memory = memory_service
        self.knowledge = knowledge_retriever
        self.metrics = metrics or Metrics()

        self.session_manager = SessionManager()
        self.context_loader = ContextLoader(memory_service)
        self.tool_matcher = ToolMatcher()
        self.router = Router(llm_client, self.tool_matcher)
        self.validation_gate = ValidationGate(domain_registry)
        self.tool_executor = ToolExecutor(domain_registry)
        self.context_builder = ContextBuilder()
        self.generator = Generator(llm_client)
        # 上一个活跃 session（检测切换 → 触发旧 session 的会话级记忆提炼）
        self._last_session_id: str | None = None

    async def initialize(self) -> None:
        """初始化：加载所有领域包并构建向量索引。"""
        from app.domain_packs.metacare import create_metacare_pack

        metacare = create_metacare_pack()
        await self.registry.register(metacare)

        self.tool_matcher.add_aliases({
            # 塔罗
            "抽一张": "tarot_draw", "抽塔罗": "tarot_draw",
            "塔罗": "tarot_draw", "占卜": "tarot_draw",
            "抽牌": "tarot_draw", "三张牌": "tarot_draw",
            # 星座运势
            "星座": "horoscope_daily", "运势": "horoscope_daily",
            "星座运势": "horoscope_daily", "今天运势": "horoscope_daily",
            # 本命星盘
            "星盘": "birth_chart", "本命盘": "birth_chart",
            "出生盘": "birth_chart", "我的星盘": "birth_chart",
            "上升星座": "birth_chart", "月亮星座": "birth_chart",
            "太阳星座": "birth_chart",
            # 流年星象
            "流年": "daily_transit", "行运": "daily_transit",
            "流年运势": "daily_transit", "星象": "daily_transit",
            "Transit": "daily_transit",
            # 主题词 → 多工具候选（星座运势含各维度 + 塔罗可细问）
            "财运": ["horoscope_daily", "tarot_draw"],
            "财富": ["horoscope_daily", "tarot_draw"],
            "钱": ["horoscope_daily", "tarot_draw"],
            "爱情": ["horoscope_daily", "tarot_draw"],
            "感情": ["horoscope_daily", "tarot_draw"],
            "恋爱": ["horoscope_daily", "tarot_draw"],
            "桃花": ["horoscope_daily", "tarot_draw"],
            "事业": ["horoscope_daily", "tarot_draw"],
            "工作": ["horoscope_daily", "tarot_draw"],
            "健康": ["horoscope_daily", "tarot_draw"],
            "学业": ["horoscope_daily", "tarot_draw"],
            # 12 星座 → fallback
            "白羊座": "horoscope_daily", "金牛座": "horoscope_daily",
            "双子座": "horoscope_daily", "巨蟹座": "horoscope_daily",
            "狮子座": "horoscope_daily", "处女座": "horoscope_daily",
            "天秤座": "horoscope_daily", "天蝎座": "horoscope_daily",
            "射手座": "horoscope_daily", "摩羯座": "horoscope_daily",
            "水瓶座": "horoscope_daily", "双鱼座": "horoscope_daily",
        })

        all_tools = self.registry.get_all_tools()
        await self.tool_matcher.rebuild_index(all_tools)

        logger.info(
            f"领域包已加载: {self.registry.get_active_domain_ids()}"
            f" 工具: {[t.tool_id for t in all_tools]}"
        )

    # ── 主请求入口 ───────────────────────────────

    async def handle_chat(self, req: ChatRequest) -> ChatResponse:
        """处理一次对话请求——完整流水线 + 全链路日志 + 澄清闸门。"""
        t0 = time.monotonic()
        user_id = "default"
        request_id = f"req_{int(t0 * 1000)}"

        rlog = RequestLogger(
            request_id=request_id,
            user_id=user_id,
            user_message=req.message[:100],
        )
        rlog.step("收到用户消息", message=req.message[:80])

        total_tokens = 0

        # ── Step 1: SessionManager ──────────────
        t1 = rlog.step("Step 1/7 SessionManager 定位/创建会话")
        session = await self.session_manager.get_or_create(
            req.session_id, user_id
        )
        session_id = session.session_id
        rlog.session_id = session_id
        rlog.step_done(t1, session_id=session_id, status=session.status)

        # ── Session 切换 → 异步提炼旧会话的长期记忆 ──
        # 用户开启新会话 = 旧会话"结束"的时机：用全量对话上下文让 LLM
        # 判断画像/长期事实/偏好（能区分"我朋友白羊座"≠用户自己）。
        # 提炼所有未标记的旧会话（幂等），不依赖单一"上一个会话"槽位——
        # 某次提炼若因时序读空失败，下次切换会自动补提炼。
        if self._last_session_id and self._last_session_id != session_id:
            asyncio.create_task(
                self._extract_stale_sessions(user_id, session_id)
            )
            rlog.log_memory_operation(
                "extract", "session",
                f"会话切换，异步提炼旧会话的长期记忆（active={session_id}）",
            )
        self._last_session_id = session_id

        # ── Step 2: ContextLoader ───────────────
        t2 = rlog.step("Step 2/7 ContextLoader 加载四层记忆")
        context = await self.context_loader.load(session_id, user_id)

        profile = await self.memory.get_profile(user_id)
        if not profile.is_empty:
            rlog.log_memory_operation("recall", "L0", profile.summary())
        else:
            rlog.log_memory_operation("recall", "L0", "画像为空")

        rlog.step_done(t2)

        # ── Step 3: Router（LLM 决策点①）────
        # 读取待澄清状态作为 Router 上下文——由 Router 判断：
        # 用户在回答澄清（输出 clarify_params）还是转新话题（正常路由）
        pending = await self.memory.get_pending_clarification(session_id)
        resume_tool_id: str | None = None
        clarify_hints: dict = {}

        t3 = rlog.step("Step 3/7 Router LLM① 意图+工具选择")
        decision = await self.router.route(
            req.message, context,
            request_id=request_id,
            session_id=session_id,
            pending=pending,
        )
        rlog.log_router_decision(
            candidates=[],
            intent=decision.intent,
            tool_selections=decision.tool_selections,
            reasoning=decision.reasoning,
        )
        total_tokens += self.router.last_tokens_in + self.router.last_tokens_out
        rlog.step_done(t3, intent=decision.intent)

        # ── Step 3.5: 澄清判断（Router 决策的一部分）──
        # 存在 pending 时的三种信号（显式标志位优先于隐式提取）：
        #   abandon_clarify=true  → 用户转新话题，无条件放弃澄清（即使误填 clarify_params）
        #   clarify_params 非空   → 用户在回答澄清，累积参数，还缺继续问
        #   两者都没有            → 无回答信号，视为转新话题，放弃 pending
        if pending and decision.abandon_clarify:
            # 显式放弃：清除 pending，忽略可能误填的 clarify_params
            decision.clarify_params = {}
            await self.memory.clear_pending_clarification(session_id)
            rlog.log_memory_operation(
                "clarify", "L0",
                "用户放弃澄清转新话题（abandon_clarify=true），丢弃待澄清状态"
            )
        elif pending and decision.clarify_params:
            tool_id = pending.get("tool_id") or ""
            tool = self.registry.get_tool(tool_id) if tool_id else None
            partial = (pending or {}).get("partial_params") or {}

            if tool is None:
                # pending 数据异常 → 清掉，按 Router 正常决策走
                await self.memory.clear_pending_clarification(session_id)
                rlog.log_memory_operation(
                    "clarify", "L0", f"pending 工具不存在，丢弃: {tool_id}"
                )
            else:
                # 累积已收集参数（本轮优先覆盖）
                merged = {**partial, **decision.clarify_params}
                rlog.log_memory_operation(
                    "clarify", "L0", f"累积参数: {merged}"
                )
                # 重新校验还缺什么
                still_missing = tool.validate_params(
                    self._merge_tool_params({}, profile, merged)
                )
                if still_missing:
                    # 还缺 → 更新 pending 累积，继续澄清（只问仍缺的）
                    ask = self._build_clarification_message(tool_id, still_missing)
                    await self.memory.update_pending_clarification(
                        session_id, still_missing, merged, ask
                    )
                    rlog.log_complete(
                        intent="clarification", tool_calls=[],
                        total_tokens=total_tokens,
                    )
                    return ChatResponse(
                        session_id=session_id,
                        reply=ask,
                        intent="clarification",
                        clarification=still_missing,
                    )
                # 齐了 → 清除 pending，恢复执行原工具
                await self.memory.clear_pending_clarification(session_id)
                resume_tool_id = tool_id
                clarify_hints = merged
                rlog.log_memory_operation(
                    "clarify", "L0",
                    f"参数齐备，恢复执行 {tool_id}: {merged}"
                )
        elif pending:
            # 无回答信号（既没标 abandon 也没提取参数）→ 视为转新话题，丢弃 pending
            await self.memory.clear_pending_clarification(session_id)
            rlog.log_memory_operation(
                "clarify", "L0", "无澄清回答信号，丢弃待澄清状态"
            )
        # 无 pending 时 clarify_params 即使被误填也忽略（不会进入累积逻辑）

        # 澄清参数齐备后：恢复执行原工具（覆盖 Router 决策）
        if resume_tool_id:
            from app.agent.router import RouterDecision, ToolSelection
            decision = RouterDecision(
                intent="execute",
                reasoning=f"澄清恢复：参数齐备，继续执行 {resume_tool_id}",
                tool_selections=[
                    ToolSelection(tool_id=resume_tool_id, params={})
                ],
            )
            rlog.step("Step 3.5/8 澄清恢复：覆盖决策，执行原工具")

        # ── Step 4: ValidationGate ──────────────
        t4 = rlog.step("Step 4/7 ValidationGate 校验")
        validation = self.validation_gate.validate(decision)
        rlog.step_done(t4,
                       valid=len(validation.valid),
                       invalid=len(validation.invalid))

        # ── 分支：execute 但无有效工具（LLM 输出异常）──
        if decision.intent == "execute" and not validation.valid:
            reply = (
                "我能帮你算塔罗、看星盘、查流年或每日运势～ "
                "你想具体来点什么？比如「帮我抽三张塔罗」或「看看我的星盘」。"
            )
            rlog.log_complete(
                intent="direct", tool_calls=[],
                total_tokens=total_tokens,
            )
            asyncio.create_task(
                self.memory.ingest(session_id, user_id, {
                    "user_message": req.message,
                    "assistant_reply": reply,
                    "intent": "direct",
                    "tool_results": [],
                })
            )
            return ChatResponse(
                session_id=session_id, reply=reply, intent="direct",
            )

        # ── 分支：direct ──
        if decision.intent == "direct":
            reply = decision.response_direct or await self._direct_reply(req.message)
            rlog.log_complete(
                intent="direct", tool_calls=[],
                total_tokens=total_tokens,
            )
            asyncio.create_task(
                self.memory.ingest(session_id, user_id, {
                    "user_message": req.message,
                    "assistant_reply": reply,
                    "intent": "direct",
                    "tool_results": [],
                })
            )
            return ChatResponse(
                session_id=session_id, reply=reply, intent="direct",
            )

        # ── Step 5: 画像注入 + 参数检查（澄清闸门）─
        t5 = rlog.step("Step 5/7 画像注入 + 参数完备性检查")
        exec_ctx = ExecutionContext(
            session_id=session_id, user_id=user_id, request_id=request_id,
        )
        tool_ids_and_params = [
            (s.tool_id, self._sanitize_params(s.tool_id, s.params))
            for s in validation.valid
        ]

        # 画像参数自动注入（画像 + 澄清回答提取的信息）
        inject_source = self._merge_tool_params({}, profile, clarify_hints)

        if inject_source:
            injected = False
            for i, (tool_id, params) in enumerate(tool_ids_and_params):
                patched = {k: v for k, v in params.items() if v is not None}
                for pkey, pval in inject_source.items():
                    if not pval:
                        continue
                    if not patched.get(pkey):
                        patched[pkey] = pval
                        injected = True
                tool_ids_and_params[i] = (tool_id, patched)
            if injected:
                rlog.log_memory_operation(
                    "inject", "L0",
                    f"自动注入画像参数: {inject_source}"
                )

        # ── 澄清闸门：缺参则返回澄清，不执行工具 ──
        for tool_id, params in tool_ids_and_params:
            tool = self.registry.get_tool(tool_id)
            if tool is None:
                continue
            missing = tool.validate_params(params)
            if missing:
                ask_message = self._build_clarification_message(
                    tool_id, missing
                )
                rlog.step_done(t5, clarification=f"tool={tool_id} missing={missing}")
                rlog.log_complete(
                    intent=decision.intent, tool_calls=[],
                    total_tokens=total_tokens,
                )
                # 记录待澄清状态，用户回答后恢复
                # 先确保 user_profiles 存在（pending_clarifications 有 FK 引用）
                await self.memory._ensure_profile(user_id)
                await self.memory.set_pending_clarification(
                    session_id, user_id, tool_id, missing, ask_message,
                )
                return ChatResponse(
                    session_id=session_id,
                    reply=ask_message,
                    intent="clarification",
                    clarification=missing,
                )

        # ── Step 6: ToolExecutor ────────────────
        t6 = rlog.step("Step 6/7 ToolExecutor 并行执行工具")
        t_tool_start = time.monotonic()
        tool_results = await self.tool_executor.execute(
            tool_ids_and_params, exec_ctx
        )

        for tr in tool_results:
            output_summary = (
                str(tr.output)[:200] if tr.output and tr.success else ""
            )
            rlog.log_tool_execution(
                tool_id=tr.tool_id,
                success=tr.success,
                elapsed_ms=(time.monotonic() - t_tool_start) * 1000,
                output_summary=output_summary,
                error=tr.error or "",
            )
        rlog.step_done(t6, tools=[tr.tool_id for tr in tool_results])

        # ── KNOWLEDGE / EXPLAIN 检索 ──
        knowledge_hits = None
        if decision.intent == "knowledge" and decision.knowledge_query:
            knowledge_hits = await self.knowledge.search(decision.knowledge_query)
        elif decision.intent == "explain" and decision.trace_lookup_index is not None:
            trace = await self.knowledge.get_trace(
                session_id, decision.trace_lookup_index
            )
            knowledge_hits = [trace] if trace else []

        # ── Step 7: ContextBuilder ──────────────
        t7 = rlog.step("Step 7/7 ContextBuilder 组装上下文+token预算")
        gen_ctx = self.context_builder.build(
            user_message=req.message,
            context=context,
            tool_results=tool_results,
            knowledge_hits=knowledge_hits,
        )
        rlog.step_done(t7)

        # ── Step 8: Generator（LLM 决策点②）───
        t8 = rlog.step("Step 8/8 Generator LLM② 汇总生成回复")
        reply = await self.generator.generate(
            gen_ctx, request_id=request_id, session_id=session_id,
        )
        total_tokens += self.generator.last_tokens_in + self.generator.last_tokens_out
        rlog.step_done(t8)

        # ── 请求完成 ────────────────────────────
        rlog.log_complete(
            intent=decision.intent,
            tool_calls=[tr.tool_id for tr in tool_results],
            total_tokens=total_tokens,
        )

        # ── 异步 Ingest（会话状态/玄学记录落库）───────
        # 画像提取在 ingest 内做"仅强自指"即时判断（"我是/我的"）；
        # 澄清回答/替他人转述的归属判断由会话级提炼负责（不在此透传
        # expect_fields——历史版本因此把"他是白羊座"写进用户画像）。
        asyncio.create_task(
            self.memory.ingest(
                session_id=session_id,
                user_id=user_id,
                turn={
                    "user_message": req.message,
                    "assistant_reply": reply,
                    "intent": decision.intent,
                    "tool_results": [
                        {"tool_id": r.tool_id, "success": r.success}
                        for r in tool_results
                    ],
                },
            )
        )

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            intent=decision.intent,
            tool_calls=[r.tool_id for r in tool_results],
        )

    async def _extract_stale_sessions(
        self, user_id: str, active_session_id: str
    ) -> None:
        """补提炼所有未提炼的旧会话（幂等，memory_extractions 标记防重）。"""
        from app.storage.database import db_fetch_all

        rows = await db_fetch_all(
            "SELECT DISTINCT session_id FROM session_state "
            "WHERE user_id=? AND session_id != ? "
            "AND session_id NOT IN (SELECT session_id FROM memory_extractions)",
            (user_id, active_session_id),
        )
        for r in rows:
            await self.memory.extract_session_memory(
                r["session_id"], user_id
            )

    # ── 澄清辅助 ─────────────────────────────────

    # 占位符/描述性文字当参数值（小模型幻觉产物）——必须丢弃，否则工具
    # 解析失败 → Generator 编造回复。真实事故：qwen 输出 sign="user提供的星座名"。
    _PLACEHOLDER_VALUE_RE = re.compile(
        r"用户(?:提供|说的|给的|消息|输入)|提供的|星座名|待补充|占位|"
        r"placeholder|unknown|n/?a|xxx+|your\s+\w+",
        re.IGNORECASE,
    )

    def _sanitize_params(self, tool_id: str, params: dict) -> dict:
        """清洗 Router 填的参数——占位值置空，走画像注入/澄清接管。"""
        out = dict(params)
        for k, v in list(out.items()):
            if isinstance(v, str) and self._PLACEHOLDER_VALUE_RE.search(v):
                logger.warning(
                    f"参数占位符清洗: tool={tool_id} param={k} "
                    f"value={v!r} → 置空"
                )
                out[k] = ""
        return out

    @staticmethod
    def _merge_tool_params(
        router_params: dict, profile, clarify_hints: dict
    ) -> dict:
        """合并工具参数来源（Router 填的 + 画像 + 澄清累积）。

        优先级：Router 显式填的 > 澄清回答提取的 > 画像存储的。
        返回注入源 dict（仅非空值）。
        """
        merged: dict = {}
        # 画像（最低优先级）
        if profile is not None and not profile.is_empty:
            for pkey, pval in (
                ("birth_date", profile.birth_date),
                ("birth_time", profile.birth_time),
                ("sign", profile.zodiac_sign),
            ):
                if pval:
                    merged[pkey] = pval
        # 澄清累积（中间优先级；zodiac_sign 映射为工具参数 sign）
        for k, v in (clarify_hints or {}).items():
            if not v:
                continue
            merged["sign" if k == "zodiac_sign" else k] = v
        # Router 显式填的（最高优先级）
        for k, v in (router_params or {}).items():
            if v:
                merged[k] = v
        return merged

    def _build_clarification_message(
        self, tool_id: str, missing: list[str]
    ) -> str:
        """根据缺失字段生成友好的澄清问题。"""
        need = ",".join(missing)

        if tool_id in ("birth_chart", "daily_transit") and "birth_date" in need:
            return (
                "算这个需要你的出生日期哦～ 方便告诉我你的生日吗？"
                "（格式如：1995年6月15日，最好带上出生时间会更准）"
            )
        if tool_id == "horoscope_daily":
            return (
                "想看今日运势需要先知道你的星座或生日～ "
                "告诉我你的星座（如\"我是白羊座\"）或生日（如\"1995年6月15日\"）都可以。"
            )
        return f"这个功能需要你提供一些信息：{need}。方便补充一下吗？"

    async def _direct_reply(self, message: str) -> str:
        return f"你好！我是 Mysu，你的玄学陪伴助手。关于「{message[:30]}...」，有什么我可以帮你的吗？"
