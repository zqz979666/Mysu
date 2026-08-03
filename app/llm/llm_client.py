"""
LLM 客户端——模型网关，统一通过 OpenAI SDK 调用多种模型。

整个 runtime 只有 Router 和 Generator 两个地方同步调用 LLM。
（MemoryService.ingest 的调用是异步的，不计入请求路径。）

面试话术：
  "我们用 OpenAI SDK 做了一层薄网关——本质是一个 dict[str, OpenAI]，
   按 model 名路由到不同 provider。不是自研，是薄封装。
   价值在于：切换模型不需要改代码，改 config.yaml 一行就行。"
"""

import time
import asyncio
import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import ModelGatewayConfig, ProviderConfig
from app.observability.logger import logger


# ── 调用结果 ────────────────────────────────────────────────

@dataclass
class LLMCallResult:
    """LLM 调用结果"""
    content: str
    structured_output: dict | None = None   # 解析后的 JSON（如有 response_format）
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class LLMCallConfig:
    """单次调用的配置"""
    system_prompt: str
    user_prompt: str
    response_format: dict | None = None    # JSON Schema（Router 结构化输出用）
    max_tokens: int | None = None           # None 则用配置默认值
    temperature: float | None = None        # None 则用配置默认值
    model: str | None = None                # None 则用配置 default_model


# ── 模型网关 ────────────────────────────────────────────────

class LLMClient:
    """模型网关——按 model 名路由到不同的 OpenAI-compatible provider。

    面试话术：
      "这不是自研的 LLM 框架。就是一个 dict[str, AsyncOpenAI]，
      构造函数里按 config.providers 建 client。call() 的时候
      按 model 名 O(1) 查到对应 client，其余全部透传给 OpenAI SDK。"
    """

    def __init__(self, config: ModelGatewayConfig):
        self.config = config

        # ── 为每个 provider 建一个 AsyncOpenAI client ──────
        self._clients: dict[str, AsyncOpenAI] = {}
        self._model_to_provider: dict[str, str] = {}

        for provider in config.providers:
            client = AsyncOpenAI(
                base_url=provider.base_url,
                api_key=provider.api_key,
                timeout=config.request_timeout,
            )
            self._clients[provider.name] = client
            for model in provider.models:
                self._model_to_provider[model] = provider.name

    # ── 对外接口 ───────────────────────────────────────

    async def call(self, config: LLMCallConfig) -> LLMCallResult:
        """同步 LLM 调用（带重试 + token 埋点）。

        Args:
            config: 调用配置

        Returns:
            LLMCallResult

        Raises:
            RuntimeError: 所有重试耗尽后仍失败
        """
        t0 = time.monotonic()

        model = config.model or self.config.default_model
        provider_name = self._model_to_provider.get(model)
        if provider_name is None:
            raise RuntimeError(
                f"模型 '{model}' 未找到对应的 provider。"
                f" 可用模型: {list(self._model_to_provider.keys())}"
            )

        client = self._clients[provider_name]
        temperature = (
            config.temperature
            if config.temperature is not None
            else self.config.default_temperature
        )
        max_tokens = config.max_tokens or self.config.default_max_tokens

        # ── 构造消息 ──────────────────────────────────
        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": config.user_prompt},
        ]

        # ── 结构化输出：统一用 json_object 模式（兼容所有 provider） ──
        extra_kwargs: dict = {}
        if config.response_format is not None:
            extra_kwargs["response_format"] = {"type": "json_object"}
            # 把 schema 注入 system prompt（兼容不支持 json_schema 的 provider）
            schema_str = json.dumps(config.response_format, ensure_ascii=False)
            messages[0]["content"] += (
                f"\n\n你必须返回一个 JSON 对象，严格遵循以下 schema:\n{schema_str}"
            )

        # ── 重试循环 ──────────────────────────────────
        last_error: str | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra_kwargs,
                )
                choice = response.choices[0]
                content = choice.message.content or ""

                # 解析结构化输出
                structured = None
                if config.response_format is not None:
                    try:
                        structured = json.loads(content)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"LLM 返回的不是合法 JSON，将作为纯文本处理。"
                            f" model={model} raw={content[:200]}"
                        )
                        structured = None
                        # 如果是 Router 调用且结构化输出必须，在 prompt 里已说明
                        # 这里不抛异常——让上层根据 None 走 fallback

                usage = response.usage
                result = LLMCallResult(
                    content=content,
                    structured_output=structured,
                    tokens_in=usage.prompt_tokens if usage else 0,
                    tokens_out=usage.completion_tokens if usage else 0,
                    model=model,
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

                logger.debug(
                    f"LLM call ok model={model} provider={provider_name}"
                    f" tokens_in={result.tokens_in} tokens_out={result.tokens_out}"
                    f" latency={result.latency_ms:.0f}ms"
                )
                return result

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"LLM call attempt {attempt}/{self.config.max_retries} failed:"
                    f" model={model} provider={provider_name} error={last_error}"
                )
                if attempt < self.config.max_retries:
                    delay = 2 ** attempt
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"LLM 调用失败（{self.config.max_retries} 次重试后）:"
            f" model={model} error={last_error}"
        )

    # ── 健康检查 ───────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """是否有至少一个可用 provider"""
        return len(self._clients) > 0 and len(self._model_to_provider) > 0

    @property
    def available_models(self) -> list[str]:
        return list(self._model_to_provider.keys())
