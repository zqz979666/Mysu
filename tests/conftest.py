"""pytest 共享 fixtures。

核心设计：
- FakeGateway：真实 LLMClient（保留重试/落表/schema回显检测逻辑）+ mock 底层
  OpenAI API。按 system prompt 内容区分 router/generator/ingest 调用，
  从脚本队列返回预设响应。记录每一次完整调用（含 messages）供断言。
- agent_service：真实 DomainRegistry + metacare 领域包 + 临时 SQLite，
  与生产唯一的区别是 LLM 走 FakeGateway。
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 保证 `import app.*` 可用（pytest 从项目根运行时通常已可，双保险）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 压掉请求/DB 流水日志，保持测试输出干净
logging.getLogger("mysu").setLevel(logging.WARNING)


# ── Fake LLM 网关 ───────────────────────────────────────────────

class FakeGateway:
    """真实 LLMClient + 可编程的 mock 底层 API。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        from app.config import ModelGatewayConfig, ProviderConfig
        from app.llm.llm_client import LLMClient

        cfg = ModelGatewayConfig(
            default_model="fake-model",
            default_max_tokens=512,
            default_temperature=0.0,
            max_retries=2,
            request_timeout=5,
            providers=[
                ProviderConfig(
                    name="fake",
                    base_url="http://fake.local/v1",
                    api_key="test-key",
                    models=["fake-model"],
                )
            ],
        )
        self.client = LLMClient(cfg)

        # 可编程响应脚本
        self.router_script: list[dict] = []   # 按序弹出的 router 结构化输出
        self.generator_reply: str = "好的～这是给你的回复。"
        self.ingest_output: dict = {}          # 画像提取的返回
        self.memory_extract_output: dict = {   # 会话级记忆提炼的返回
            "profile": {}, "facts": [], "preferences": {},
        }
        self.fail_before: int = 0              # 前 N 次调用抛异常（测重试）
        self.calls: list[dict] = []            # 完整调用 kwargs（含 messages）

        async def fake_create(**kwargs):
            self.calls.append(kwargs)
            if self.fail_before > 0:
                self.fail_before -= 1
                raise RuntimeError("simulated network failure")
            content = self._dispatch(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=content))
                ],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            )

        monkeypatch.setattr(
            self.client._clients["fake"], "chat",
            SimpleNamespace(completions=SimpleNamespace(create=fake_create)),
        )

    def _dispatch(self, kwargs: dict) -> str:
        system = kwargs["messages"][0]["content"]
        if "意图路由器" in system:
            raw = self.router_script.pop(0) if self.router_script else {
                "intent": "direct", "response_direct": "你好，我是 Mysu。"
            }
            return json.dumps(raw, ensure_ascii=False)
        if "心理陪伴助手" in system:  # generator
            return self.generator_reply
        if "信息提取器" in system:    # ingest 画像提取
            return json.dumps(self.ingest_output, ensure_ascii=False)
        if "记忆提炼器" in system:    # 会话级记忆提炼
            return json.dumps(self.memory_extract_output, ensure_ascii=False)
        return "{}"

    # ── 便捷设置 ──────────────────────────────
    def set_router(self, raw: dict) -> None:
        self.router_script.append(raw)

    def set_generator(self, reply: str) -> None:
        self.generator_reply = reply

    def set_ingest(self, output: dict) -> None:
        self.ingest_output = output

    def set_memory_extract(self, output: dict) -> None:
        self.memory_extract_output = output

    @property
    def router_calls(self) -> list[dict]:
        return [c for c in self.calls if "意图路由器" in c["messages"][0]["content"]]

    @property
    def generator_calls(self) -> list[dict]:
        return [c for c in self.calls if "心理陪伴助手" in c["messages"][0]["content"]]

    @property
    def ingest_calls(self) -> list[dict]:
        return [c for c in self.calls if "信息提取器" in c["messages"][0]["content"]]

    @property
    def memory_extract_calls(self) -> list[dict]:
        return [c for c in self.calls if "记忆提炼器" in c["messages"][0]["content"]]

    async def wait_async_calls(self, n: int = 0, timeout: float = 2.0) -> None:
        """等待异步任务（ingest 落表）跑完。"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if n == 0 or len(self.calls) >= n:
                await asyncio.sleep(0.02)
                return
            await asyncio.sleep(0.02)
        raise TimeoutError(f"等待 LLM 调用数 >= {n} 超时（当前 {len(self.calls)}）")

    async def wait_for_call_type(self, marker: str, timeout: float = 2.0) -> None:
        """等待出现某种类型的 LLM 调用（如会话级提炼）。"""
        await self.wait_for_call_type_count(marker, 1, timeout)

    async def wait_for_call_type_count(
        self, marker: str, min_count: int, timeout: float = 2.0
    ) -> None:
        """等待某种类型的 LLM 调用数达到 min_count（用于断言"新增"调用）。"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            n = sum(1 for c in self.calls if marker in c["messages"][0]["content"])
            if n >= min_count:
                return
            await asyncio.sleep(0.02)
        raise TimeoutError(f"等待调用类型 {marker!r} 达到 {min_count} 次超时")


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    """独立临时数据库（每次测试新建）。"""
    from app.storage.database import init_db
    path = str(tmp_path / "mysu_test.db")
    init_db(path)
    return path


@pytest.fixture
def memory_service(tmp_db_path):
    """无 LLM 的 MemoryService（画像提取走 regex 兜底）。"""
    from app.memory.memory_service import MemoryService
    return MemoryService(db_path=tmp_db_path, llm_client=None)


@pytest.fixture
def fake_gateway(monkeypatch) -> FakeGateway:
    return FakeGateway(monkeypatch)


@pytest.fixture
async def agent_service(tmp_db_path, fake_gateway):
    """完整 AgentService：真实注册表 + metacare 包 + FakeGateway LLM。"""
    from app.agent.agent_service import AgentService
    from app.domain.domain_registry import DomainRegistry
    from app.knowledge.knowledge_retriever import KnowledgeRetriever
    from app.memory.memory_service import MemoryService
    from app.observability.metrics import Metrics

    registry = DomainRegistry()
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    svc = AgentService(
        llm_client=fake_gateway.client,
        domain_registry=registry,
        memory_service=memory,
        knowledge_retriever=KnowledgeRetriever(),
        metrics=Metrics(),
    )
    await svc.initialize()
    return svc


@pytest.fixture
def chat_request():
    """构造 ChatRequest 的工厂。"""
    from app.models.requests import ChatRequest

    def _make(message: str, session_id: str = "test-session"):
        return ChatRequest(message=message, session_id=session_id)

    return _make
