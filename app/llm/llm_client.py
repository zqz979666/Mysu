"""
LLM 客户端——统一调用 / 重试 / token 埋点

整个 runtime 只有 Router 和 Generator 两个地方同步调用 LLM。
（MemoryService.ingest 的调用是异步的，不计入请求路径。）
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMCallResult:
    """LLM 调用结果"""

    content: str
    structured_output: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class LLMCallConfig:
    """单次调用的配置"""

    system_prompt: str
    user_prompt: str
    response_format: dict | None = None  # structured output JSON Schema
    max_tokens: int = 2048
    temperature: float = 0.7


class LLMClient:
    """统一的 LLM 调用接口。

    职责：
    1. 封装 provider 差异（未来可切换 OpenAI / 本地模型）
    2. 统一重试策略（指数退避，最多 3 次）
    3. token 用量埋点（给 Observability）
    4. 结构化输出（response_format → JSON Schema）
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "qwen2.5:7b",
        max_retries: int = 3,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries

    async def call(self, config: LLMCallConfig) -> LLMCallResult:
        """同步 LLM 调用（带重试 + 埋点）。

        TODO: 对接真实 LLM API（OpenAI SDK / httpx）。
        当前返回占位结果。
        """
        t0 = time.monotonic()

        # ── 重试 ──────────────────────────────────
        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._do_call(config)
                result.latency_ms = (time.monotonic() - t0) * 1000
                # ── 埋点 ──────────────────────────
                # metrics.record_llm_call(result)
                return result
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

        raise RuntimeError(
            f"LLM call failed after {self.max_retries} retries: {last_error}"
        )

    async def _do_call(self, config: LLMCallConfig) -> LLMCallResult:
        """实际的单次 API 调用。

        TODO: 对接真实 API。当前返回占位结果以验证管道连通。
        """
        # ── 占位实现 ──────────────────────────────
        return LLMCallResult(
            content=f"[LLM 占位回复] system={config.system_prompt[:50]}... user={config.user_prompt[:50]}...",
            structured_output=None,
            tokens_in=len(config.system_prompt) // 4 + len(config.user_prompt) // 4,
            tokens_out=64,
            model=self.model,
        )
