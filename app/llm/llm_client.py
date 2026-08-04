"""
LLM 客户端——模型网关，统一通过 OpenAI SDK 调用多种模型。

每次调用自动落表 llm_call_logs（异步、非阻塞）。
"""

import time
import asyncio
import json
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import ModelGatewayConfig
from app.observability.logger import logger


# ── 调用结果 ────────────────────────────────────────────────

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
    response_format: dict | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    model: str | None = None
    # 调用上下文（用于落表）
    call_type: str = ""        # "router" | "generator" | "ingest"
    request_id: str = ""
    session_id: str = ""


# ── 模型网关 ────────────────────────────────────────────────

class LLMClient:
    """模型网关 + LLM 调用日志落表。"""

    def __init__(self, config: ModelGatewayConfig):
        self.config = config

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
        """同步 LLM 调用（带重试 + 日志落表）。

        Args:
            config: 调用配置（含 call_type/request_id/session_id 用于落表）
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

        extra_kwargs: dict = {}
        if config.response_format is not None:
            extra_kwargs["response_format"] = {"type": "json_object"}
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

                # ── 异步落表（不阻塞请求路径） ──────────
                asyncio.create_task(
                    self._log_call_to_db(
                        config=config,
                        model=model,
                        provider=provider_name,
                        result=result,
                        structured_output=structured,
                    )
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

        # ── 所有重试失败，也落表 ────────────────────────
        asyncio.create_task(
            self._log_failure_to_db(
                config=config,
                model=model,
                provider=provider_name,
                error=last_error or "unknown",
            )
        )

        raise RuntimeError(
            f"LLM 调用失败（{self.config.max_retries} 次重试后）:"
            f" model={model} error={last_error}"
        )

    async def _log_call_to_db(
        self,
        config: LLMCallConfig,
        model: str,
        provider: str,
        result: LLMCallResult,
        structured_output: dict | None,
    ) -> None:
        """将成功调用写入 llm_call_logs 表"""
        try:
            from app.storage.database import db_execute

            await db_execute(
                """INSERT INTO llm_call_logs (
                    request_id, session_id, call_type, model, provider,
                    tokens_in, tokens_out, latency_ms,
                    system_prompt_snippet, user_prompt_snippet, response_snippet,
                    structured_output_json, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    config.request_id,
                    config.session_id,
                    config.call_type,
                    model,
                    provider,
                    result.tokens_in,
                    result.tokens_out,
                    result.latency_ms,
                    config.system_prompt[:500],
                    config.user_prompt[:500],
                    result.content[:500],
                    json.dumps(structured_output, ensure_ascii=False)
                    if structured_output
                    else None,
                ),
            )
        except Exception as e:
            logger.error(f"LLM 调用日志落表失败: {e}")

    async def _log_failure_to_db(
        self,
        config: LLMCallConfig,
        model: str,
        provider: str,
        error: str,
    ) -> None:
        """将失败调用写入 llm_call_logs 表"""
        try:
            from app.storage.database import db_execute

            await db_execute(
                """INSERT INTO llm_call_logs (
                    request_id, session_id, call_type, model, provider,
                    tokens_in, tokens_out, latency_ms,
                    system_prompt_snippet, user_prompt_snippet,
                    success, error_message
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, 0, ?)""",
                (
                    config.request_id,
                    config.session_id,
                    config.call_type,
                    model,
                    provider,
                    config.system_prompt[:500],
                    config.user_prompt[:500],
                    error[:500],
                ),
            )
        except Exception as e:
            logger.error(f"LLM 失败日志落表失败: {e}")

    # ── 健康检查 ───────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return len(self._clients) > 0 and len(self._model_to_provider) > 0

    @property
    def available_models(self) -> list[str]:
        return list(self._model_to_provider.keys())
