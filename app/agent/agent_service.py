"""
AgentService——主编排器（纯函数流水线）

这是 Mysu 的核心，连接所有组件，实现请求生命周期：

入口 → SessionManager → ContextLoader → Router（LLM①）→ ValidationGate
     → ToolExecutor（并行）→ ContextBuilder → Generator（LLM②）→ 返回
     → 异步 Ingest

面试核心主张：
  整个 runtime 只有两个同步 LLM 调用点（Router + Generator）。
  LLM 只做约束下的选择与表达，所有复杂度都在确定性的编排和校验上。
"""

import time
import asyncio

from app.models.domain import ExecutionContext
from app.models.requests import ChatRequest
from app.models.responses import ChatResponse

from app.agent.session_manager import SessionManager
from app.agent.context_loader import ContextLoader
from app.agent.router import Router, RouterDecision
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
from app.observability.metrics import Metrics


class AgentService:
    """主编排器。

    使用方式：
        service = AgentService(llm_client, domain_registry, ...)
        await service.initialize()  # 加载领域包
        response = await service.handle_chat(request)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        domain_registry: DomainRegistry,
        memory_service: MemoryService,
        knowledge_retriever: KnowledgeRetriever,
        metrics: Metrics | None = None,
    ):
        # ── 基础设施 ──────────────────────────
        self.llm = llm_client
        self.registry = domain_registry
        self.memory = memory_service
        self.knowledge = knowledge_retriever
        self.metrics = metrics or Metrics()

        # ── 管道组件 ──────────────────────────
        self.session_manager = SessionManager()
        self.context_loader = ContextLoader(memory_service)
        self.tool_matcher = ToolMatcher()
        self.router = Router(llm_client, self.tool_matcher)
        self.validation_gate = ValidationGate(domain_registry)
        self.tool_executor = ToolExecutor(domain_registry)
        self.context_builder = ContextBuilder()
        self.generator = Generator(llm_client)

    async def initialize(self) -> None:
        """初始化：加载所有领域包并构建向量索引。

        TODO: 扫描 domain_packs/ 目录，加载并注册领域包。
        """
        # TODO: 后续实现领域包的自动发现和加载
        pass

    # ── 主请求入口 ───────────────────────────────

    async def handle_chat(self, req: ChatRequest) -> ChatResponse:
        """处理一次对话请求——完整的 7 步流水线。

        ┌─── 同步管道 ───────────────────────────┐
        │ 1. SessionManager  → 定位/创建会话       │
        │ 2. ContextLoader   → 加载四层记忆        │
        │ 3. Router          → LLM① 意图+工具选择   │
        │ 4. ValidationGate  → 校验 tool_id/schema │
        │ 5. ToolExecutor    → 并行执行+失败隔离    │
        │ 6. ContextBuilder  → 组装+token预算       │
        │ 7. Generator       → LLM② 汇总生成回复    │
        └─────────────────────────────────────────┘
        ┌─── 异步管道 ───────────────────────────┐
        │ 8. MemoryService.ingest  → 记忆提炼     │
        └─────────────────────────────────────────┘
        """
        t0 = time.monotonic()
        user_id = "default"  # TODO: 从请求头/认证中提取
        request_id = f"req_{int(t0 * 1000)}"

        # ── Step 1: SessionManager ──────────────
        t1 = time.monotonic()
        session = await self.session_manager.get_or_create(
            req.session_id, user_id
        )
        session_id = session.session_id
        lat_session = (time.monotonic() - t1) * 1000

        # ── Step 2: ContextLoader ───────────────
        t2 = time.monotonic()
        context = await self.context_loader.load(session_id, user_id)
        lat_context = (time.monotonic() - t2) * 1000

        # ── Step 3: Router（LLM 决策点①）────────
        t3 = time.monotonic()
        decision = await self.router.route(req.message, context)
        lat_router = (time.monotonic() - t3) * 1000

        # ── Step 4: ValidationGate ──────────────
        validation = self.validation_gate.validate(decision)
        # TODO: 校验失败时的降级策略（清除无效选择，或无工具时降级为 direct）

        # ── 分支：direct 意图直接跳过工具执行 ──
        if decision.intent == "direct":
            reply = decision.response_direct or await self._direct_reply(req.message)
            lat_total = (time.monotonic() - t0) * 1000
            return ChatResponse(
                session_id=session_id,
                reply=reply,
                intent=decision.intent,
            )

        # ── Step 5: ToolExecutor ────────────────
        t5 = time.monotonic()
        exec_ctx = ExecutionContext(
            session_id=session_id,
            user_id=user_id,
            request_id=request_id,
        )
        tool_ids_and_params = [
            (s.tool_id, s.params) for s in validation.valid
        ]
        tool_results = await self.tool_executor.execute(
            tool_ids_and_params, exec_ctx
        )
        lat_tool = (time.monotonic() - t5) * 1000

        # ── 分支：KNOWLEDGE / EXPLAIN 检索知识 ──
        knowledge_hits = None
        if decision.intent == "knowledge" and decision.knowledge_query:
            knowledge_hits = await self.knowledge.search(
                decision.knowledge_query
            )
        elif decision.intent == "explain" and decision.trace_lookup_index is not None:
            trace = await self.knowledge.get_trace(
                session_id, decision.trace_lookup_index
            )
            knowledge_hits = [trace] if trace else []

        # ── Step 6: ContextBuilder ──────────────
        t6 = time.monotonic()
        gen_ctx = self.context_builder.build(
            user_message=req.message,
            context=context,
            tool_results=tool_results,
            knowledge_hits=knowledge_hits,
        )

        # ── Step 7: Generator（LLM 决策点②）────
        reply = await self.generator.generate(gen_ctx)
        lat_total = (time.monotonic() - t0) * 1000

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

        # ── 返回 ─────────────────────────────────
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            intent=decision.intent,
            tool_calls=[r.tool_id for r in tool_results],
        )

    async def _direct_reply(self, message: str) -> str:
        """direct 意图的简短回复（无 Router 结构化输出时 fallback）"""
        return f"你好！我是 Mysu，你的玄学陪伴助手。关于「{message[:30]}...」，有什么我可以帮你的吗？"
