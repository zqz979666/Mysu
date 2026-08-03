"""
Mysu — 玄学陪伴 Agent（本地服务）

FastAPI 入口：对接 AgentService 管道

启动：
    ./run.sh
    或
    env -u PYTHONPATH .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8008

API：
    GET  /api/health         健康检查
    POST /api/chat           对话（7 步流水线）
    POST /api/events/pending 拉取待推送事件（客户端轮询）
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.models.requests import ChatRequest, EventsPendingRequest
from app.models.responses import (
    ChatResponse,
    EventsPendingResponse,
    ErrorResponse,
)
from app.llm.llm_client import LLMClient
from app.domain.domain_registry import DomainRegistry, get_registry
from app.memory.memory_service import MemoryService
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.agent.agent_service import AgentService
from app.observability.logger import logger
from app.observability.metrics import get_metrics


# ── 全局服务实例（应用启动时注入）─────────────
agent_service: AgentService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global agent_service

    logger.info("Mysu 启动中...")

    # ── 初始化基础设施 ────────────────────────
    llm_client = LLMClient()
    registry = get_registry()
    memory_service = MemoryService()
    knowledge_retriever = KnowledgeRetriever()
    metrics = get_metrics()

    # ── 组装 AgentService ─────────────────────
    agent_service = AgentService(
        llm_client=llm_client,
        domain_registry=registry,
        memory_service=memory_service,
        knowledge_retriever=knowledge_retriever,
        metrics=metrics,
    )

    await agent_service.initialize()
    logger.info("Mysu 启动完成")

    yield

    logger.info("Mysu 关闭")


app = FastAPI(
    title="Mysu",
    version="0.2.0",
    description="玄学陪伴 Agent — 本地服务",
    lifespan=lifespan,
)


# ── 路由 ──────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """对话接口——完整的 7 步 AgentService 流水线。

    请求生命周期：
    入口 → SessionManager → ContextLoader → Router（LLM①）
    → ValidationGate → ToolExecutor（并行）→ ContextBuilder
    → Generator（LLM②）→ 返回 → 异步 Ingest
    """
    try:
        response = await agent_service.handle_chat(req)
        return response
    except Exception as e:
        logger.exception("chat 请求处理失败")
        # 返回错误响应（保持 ChatResponse 协议兼容，用 reply 传错误信息）
        return ChatResponse(
            session_id=req.session_id or "error",
            reply=f"抱歉，处理请求时出错了：{str(e)}",
            intent="direct",
        )


@app.post("/api/events/pending", response_model=EventsPendingResponse)
async def events_pending(req: EventsPendingRequest) -> EventsPendingResponse:
    """拉取待推送事件——客户端轮询用。

    TODO: 实现事件队列（推送消息、状态变更等）。
    当前返回空列表。
    """
    return EventsPendingResponse(events=[], latest_event_id=req.mark_id)
