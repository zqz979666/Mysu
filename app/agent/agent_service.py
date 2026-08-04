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

        # ── Step 0.5: 待澄清状态检查 ─────────────
        # 上一轮澄清过 → 本轮消息是回答 → 宽松提取画像 → 清除 pending
        pending = await self.memory.get_pending_clarification(session_id)
        if pending:
            rlog.step("澄清恢复: 用户回答，宽松提取画像")
            hints = await self.memory._extract_profile_llm(
                req.message, allow_bare=True
            )
            if hints:
                await self.memory._update_profile_from_hints(user_id, hints)
                rlog.log_memory_operation(
                    "clarify", "L0", f"从回答中提取: {hints}"
                )
            await self.memory.clear_pending_clarification(session_id)
            rlog.step_done(time.monotonic(), pending_cleared=True)

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
        t3 = rlog.step("Step 3/7 Router LLM① 意图+工具选择")
        decision = await self.router.route(
            req.message, context,
            request_id=request_id,
            session_id=session_id,
        )
        rlog.log_router_decision(
            candidates=[],
            intent=decision.intent,
            tool_selections=decision.tool_selections,
            reasoning=decision.reasoning,
        )
        total_tokens += self.router.last_tokens_in + self.router.last_tokens_out
        rlog.step_done(t3, intent=decision.intent)

        # ── Step 4: ValidationGate ──────────────
        t4 = rlog.step("Step 4/7 ValidationGate 校验")
        validation = self.validation_gate.validate(decision)
        rlog.step_done(t4,
                       valid=len(validation.valid),
                       invalid=len(validation.invalid))

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
            (s.tool_id, s.params) for s in validation.valid
        ]

        # 画像参数自动注入
        if not profile.is_empty:
            injected = False
            for i, (tool_id, params) in enumerate(tool_ids_and_params):
                patched = {k: v for k, v in params.items() if v is not None}
                if not patched.get("birth_date") and profile.birth_date:
                    patched["birth_date"] = profile.birth_date
                    injected = True
                if not patched.get("birth_time") and profile.birth_time:
                    patched["birth_time"] = profile.birth_time
                    injected = True
                if not patched.get("sign") and profile.zodiac_sign:
                    patched["sign"] = profile.zodiac_sign
                    injected = True
                tool_ids_and_params[i] = (tool_id, patched)
            if injected:
                rlog.log_memory_operation(
                    "inject", "L0",
                    f"自动注入画像参数: birth_date={profile.birth_date} "
                    f"birth_time={profile.birth_time}"
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

        # ── 画像回写：工具算出星座信息 → 存画像 ──
        await self._backfill_profile_from_tools(
            user_id, tool_results, rlog
        )

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

        # ── 异步 Ingest ─────────────────────────
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

    # ── 澄清辅助 ─────────────────────────────────

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

    # ── 画像回写 ─────────────────────────────────

    async def _backfill_profile_from_tools(
        self, user_id: str, tool_results: list, rlog: RequestLogger
    ) -> None:
        """工具执行成功后，将算出的星座信息回写画像。

        覆盖场景：用户第一次让系统算星盘/运势，
        系统从 birth_date 算出 sun/moon/ascendant——这些应该沉淀到画像，
        下次无需再算。
        """
        profile = await self.memory.get_profile(user_id)
        updates: dict = {}

        for tr in tool_results:
            if not tr.success or not tr.output:
                continue
            out = tr.output

            # 星座工具输出：抽取 sun/moon/ascendant
            for key, field in (
                ("sun_sign", "zodiac_sign"),
                ("moon_sign", "moon_sign"),
                ("ascendant", "ascendant_sign"),
            ):
                val = out.get(key, "")
                if not val:
                    continue
                # 输出格式如 "♊ 双子座" → 转英文 id
                sign_id = self._cn_sign_to_id(val)
                if sign_id and not getattr(profile, field):
                    updates[field] = sign_id

            # 确认了出生日期 → 回写
            if out.get("birth_date") and not profile.birth_date:
                updates["birth_date"] = out["birth_date"]
            if out.get("birth_time") and not profile.birth_time:
                updates["birth_time"] = out["birth_time"]

        if updates:
            await self.memory._update_profile_from_hints(user_id, updates)
            rlog.log_memory_operation(
                "backfill", "L0", f"工具结果回写画像: {updates}"
            )

    @staticmethod
    def _cn_sign_to_id(text: str) -> str:
        """中文星座名 → 英文 id，失败返回空串。"""
        _CN_TO_ID = {
            "白羊座": "aries", "金牛座": "taurus", "双子座": "gemini",
            "巨蟹座": "cancer", "狮子座": "leo", "处女座": "virgo",
            "天秤座": "libra", "天蝎座": "scorpio", "射手座": "sagittarius",
            "摩羯座": "capricorn", "水瓶座": "aquarius", "双鱼座": "pisces",
        }
        for cn, sid in _CN_TO_ID.items():
            if cn in text:
                return sid
        return ""

    async def _direct_reply(self, message: str) -> str:
        return f"你好！我是 Mysu，你的玄学陪伴助手。关于「{message[:30]}...」，有什么我可以帮你的吗？"
