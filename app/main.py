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

配置：
    config.yaml — 模型网关配置（provider / api_key / model 列表）
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import load_config, ConfigError
from app.models.requests import ChatRequest, EventsPendingRequest
from app.models.responses import (
    ChatResponse,
    EventsPendingResponse,
)
from app.llm.llm_client import LLMClient
from app.domain.domain_registry import get_registry
from app.memory.memory_service import MemoryService
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.agent.agent_service import AgentService
from app.observability.logger import logger
from app.observability.metrics import get_metrics
from app.storage.database import init_db, db_execute, db_fetch_all, db_fetch_one, get_db_path


# ── 全局服务实例（应用启动时注入）─────────────
agent_service: AgentService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期——启动时加载配置 + 校验，失败则拒绝启动。"""
    global agent_service

    logger.info("Mysu 启动中...")

    # ── 0. 初始化数据库 ─────────────────────────────
    db_path = init_db("data/mysu.db")
    logger.info(f"数据库已初始化: {db_path}")

    # ── 1. 加载模型网关配置 ────────────────────────
    try:
        model_config = load_config("config.yaml")
    except ConfigError as e:
        logger.error(f"配置加载失败: {e}")
        print(f"\n{'='*60}")
        print(f"  Mysu 启动失败：模型网关配置错误")
        print(f"  {'='*60}")
        print(f"  {e}")
        print(f"{'='*60}\n")
        raise

    logger.info(
        f"模型网关已就绪: default={model_config.default_model}"
        f" providers={[p.name for p in model_config.providers]}"
        f" models={model_config.available_models}"
    )

    # ── 2. 初始化基础设施 ──────────────────────────
    llm_client = LLMClient(model_config)
    registry = get_registry()
    memory_service = MemoryService(llm_client=llm_client)
    knowledge_retriever = KnowledgeRetriever()
    metrics = get_metrics()

    # ── 3. 组装 AgentService ───────────────────────
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
    version="0.3.0",
    description="Mysu - local service",
    lifespan=lifespan,
)


# ── 路由 ──────────────────────────────────────


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_ready": agent_service.llm.is_ready if agent_service else False,
    }


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
        return ChatResponse(
            session_id=req.session_id or "error",
            reply=f"抱歉，处理请求时出错了：{str(e)}",
            intent="direct",
        )


@app.post("/api/events/pending", response_model=EventsPendingResponse)
async def events_pending(req: EventsPendingRequest) -> EventsPendingResponse:
    """拉取待推送事件——客户端轮询用。

    TODO: 实现事件队列（推送消息、状态变更等）。
    """
    return EventsPendingResponse(events=[], latest_event_id=req.mark_id)


# ── Debug 接口 ──────────────────────────────────


@app.get("/api/debug/db")
async def debug_db_info():
    """数据库基本信息：路径、大小、表列表"""
    import os
    db_path = get_db_path()
    size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0
    tables = await db_fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return {
        "db_path": db_path,
        "size_mb": round(size_mb, 2),
        "tables": [t["name"] for t in tables],
    }


@app.get("/api/debug/profile/{user_id}")
async def debug_profile(user_id: str):
    """查询指定用户的画像"""
    row = await db_fetch_one(
        "SELECT * FROM user_profiles WHERE user_id=?", (user_id,)
    )
    if row is None:
        return {"user_id": user_id, "found": False}
    return {"user_id": user_id, "found": True, "profile": dict(row)}


@app.get("/api/debug/llm-logs")
async def debug_llm_logs(limit: int = 20):
    """查询最近的 LLM 调用记录"""
    rows = await db_fetch_all(
        "SELECT id, request_id, call_type, model, tokens_in, tokens_out, "
        "round(latency_ms,0) as latency_ms, success, "
        "substr(response_snippet, 1, 100) as response_preview, "
        "created_at "
        "FROM llm_call_logs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return {"count": len(rows), "logs": [dict(r) for r in rows]}


@app.get("/api/debug/readings/{user_id}")
async def debug_readings(user_id: str, limit: int = 10):
    """查询用户的玄学记录 (L2)"""
    rows = await db_fetch_all(
        "SELECT tool_id, query, substr(result_json,1,200) as result_preview, created_at "
        "FROM readings WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return {"user_id": user_id, "count": len(rows), "readings": [dict(r) for r in rows]}


@app.get("/api/debug/db-logs")
async def debug_db_logs(limit: int = 30, table: str = ""):
    """查询最近的数据库操作日志。

    Args:
        limit: 返回条数
        table: 按表名过滤（如 user_profiles）
    """
    if table:
        rows = await db_fetch_all(
            "SELECT id, operation, table_name, sql_snippet, row_count, "
            "round(latency_ms,1) as latency_ms, success, error_message, context, "
            "created_at FROM db_operation_logs "
            "WHERE table_name=? ORDER BY id DESC LIMIT ?",
            (table, limit),
            _log=False,
        )
    else:
        rows = await db_fetch_all(
            "SELECT id, operation, table_name, sql_snippet, row_count, "
            "round(latency_ms,1) as latency_ms, success, error_message, context, "
            "created_at FROM db_operation_logs ORDER BY id DESC LIMIT ?",
            (limit,),
            _log=False,
        )
    return {"count": len(rows), "logs": [dict(r) for r in rows]}


@app.post("/api/debug/reset-profile")
async def debug_reset_profile(user_id: str = "default"):
    """重置指定用户的画像（调试用）——级联清理子表数据。"""
    # 先删子表（外键约束），再删画像
    await db_execute("DELETE FROM session_state WHERE user_id=?", (user_id,),
                     context="debug_reset")
    await db_execute("DELETE FROM readings WHERE user_id=?", (user_id,),
                     context="debug_reset")
    await db_execute("DELETE FROM long_term_facts WHERE user_id=?", (user_id,),
                     context="debug_reset")
    await db_execute("DELETE FROM user_profiles WHERE user_id=?", (user_id,),
                     context="debug_reset")
    return {"status": "reset", "user_id": user_id,
            "cleaned": ["session_state", "readings", "long_term_facts", "user_profiles"]}
