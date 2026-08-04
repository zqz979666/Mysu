"""
请求级全链路日志上下文。

每个请求持有一个 RequestLogger 实例，贯穿整个 7 步流水线。
在每一步记录：输入、决策依据、LLM 调用细节、工具结果、耗时。

输出格式：
  [req_xxx] Step 1/7 SessionManager → session_id=xxx (12ms)
  [req_xxx] Step 3/7 Router LLM① → intent=execute tool=birth_chart
    candidates: [birth_chart, daily_transit, horoscope_daily]
    decision: intent=execute | tool_selections=birth_chart(params={...})
    LLM: model=qwen2.5:3b tokens_in=564 tokens_out=102 latency=3435ms

设计原则：
- 每个请求独立 ID，可在日志 + LLM 记录表中关联
- 关键决策点输出 WHY（为什么选这个工具/为什么是这个意图）
- LLM 调用的 prompt 摘要和 response 摘要都记录
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("mysu.request")


@dataclass
class RequestLogger:
    """请求级日志上下文——贯穿一次 chat 请求的全生命周期。"""

    request_id: str
    user_id: str
    session_id: str = ""
    user_message: str = ""

    # 各阶段耗时（ms）
    _t_start: float = field(default_factory=time.monotonic)
    _current_step: int = 0

    # ── 公共方法 ────────────────────────────────────

    def step(self, name: str, **kwargs) -> float:
        """记录一个流水线步骤的开始。

        Returns:
            本步骤的开始时间（用于手动计算耗时）
        """
        self._current_step += 1
        elapsed = (time.monotonic() - self._t_start) * 1000
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        logger.info(
            f"[{self.request_id}] Step {self._current_step}: {name}"
            + (f" | {extra}" if extra else "")
            + f" | +{elapsed:.0f}ms"
        )
        return time.monotonic()

    def step_done(self, t_start: float, **kwargs) -> None:
        """记录步骤完成及耗时。"""
        elapsed = (time.monotonic() - t_start) * 1000
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        logger.info(
            f"[{self.request_id}]   ✓ 完成 ({elapsed:.0f}ms)"
            + (f" | {extra}" if extra else "")
        )

    # ── 专用记录方法 ────────────────────────────────

    def log_router_decision(
        self,
        candidates: list[str],
        intent: str,
        tool_selections: list,
        reasoning: str = "",
    ) -> None:
        """记录 Router 的完整决策过程。"""
        logger.info(
            f"[{self.request_id}] Router 决策: intent={intent}"
        )
        if candidates:
            logger.info(
                f"[{self.request_id}]   候选工具: {candidates}"
                f" | LLM 从中选择: {[s.tool_id for s in tool_selections] if tool_selections else '无'}"
            )
        if reasoning:
            logger.info(
                f"[{self.request_id}]   推理依据: {reasoning[:200]}"
            )
        if tool_selections:
            for ts in tool_selections:
                logger.info(
                    f"[{self.request_id}]   工具选择: {ts.tool_id} params={ts.params}"
                )

    def log_llm_call(
        self,
        call_type: str,
        model: str,
        provider: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        prompt_summary: str = "",
        response_summary: str = "",
        structured_output: dict | None = None,
    ) -> None:
        """记录一次 LLM 调用的详细信息。"""
        logger.info(
            f"[{self.request_id}] LLM 调用 ({call_type}): "
            f"model={model} provider={provider} "
            f"tokens_in={tokens_in} tokens_out={tokens_out} "
            f"latency={latency_ms:.0f}ms"
        )
        if prompt_summary:
            logger.debug(
                f"[{self.request_id}]   Prompt 摘要: {prompt_summary[:300]}"
            )
        if response_summary:
            logger.debug(
                f"[{self.request_id}]   Response 摘要: {response_summary[:300]}"
            )
        if structured_output:
            logger.debug(
                f"[{self.request_id}]   结构化输出: {structured_output}"
            )

    def log_tool_execution(
        self,
        tool_id: str,
        success: bool,
        elapsed_ms: float,
        output_summary: str = "",
        error: str = "",
    ) -> None:
        """记录一次工具执行的详细信息。"""
        status = "✓ 成功" if success else "✗ 失败"
        logger.info(
            f"[{self.request_id}] 工具执行: {tool_id} {status} "
            f"({elapsed_ms:.0f}ms)"
        )
        if output_summary:
            logger.info(
                f"[{self.request_id}]   工具输出摘要: {output_summary[:200]}"
            )
        if error:
            logger.error(
                f"[{self.request_id}]   工具错误: {error}"
            )

    def log_memory_operation(
        self, op: str, layer: str, detail: str = ""
    ) -> None:
        """记录记忆操作。"""
        logger.info(
            f"[{self.request_id}] 记忆 {op}: layer={layer}"
            + (f" | {detail}" if detail else "")
        )

    def log_complete(
        self,
        intent: str,
        tool_calls: list[str],
        total_tokens: int,
    ) -> None:
        """记录整个请求完成的总耗时和统计。"""
        total_ms = (time.monotonic() - self._t_start) * 1000
        tools_str = ", ".join(tool_calls) if tool_calls else "无"
        logger.info(
            f"[{self.request_id}] ═══ 请求完成 ═══ "
            f"intent={intent} tools=[{tools_str}] "
            f"total_tokens={total_tokens} "
            f"total_latency={total_ms:.0f}ms"
        )
