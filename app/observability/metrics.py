"""
指标埋点——记录 LLM 调用次数、token 用量、各阶段延迟。

面试话术：有了这个就能回答"整个 runtime 只有 2 次同步 LLM 调用"——
这不是感觉，是 Metrics 输出验证的。
"""

from dataclasses import dataclass, field


@dataclass
class PipelineMetrics:
    """一次请求的管道指标"""

    request_id: str = ""
    # LLM 调用次数
    router_calls: int = 0      # 永远 ≤1
    generator_calls: int = 0   # 永远 ≤1
    ingest_calls: int = 0      # 异步，不计入同步
    # token 用量
    tokens_in: int = 0
    tokens_out: int = 0
    # 各阶段延迟 (ms)
    latency_session_ms: float = 0.0
    latency_context_ms: float = 0.0
    latency_router_ms: float = 0.0
    latency_tool_exec_ms: float = 0.0
    latency_generator_ms: float = 0.0
    latency_total_ms: float = 0.0
    # 工具执行统计
    tools_called: int = 0
    tools_succeeded: int = 0
    tools_failed: int = 0


class Metrics:
    """全局指标收集器（内存计数 + 结构化日志输出）"""

    def __init__(self):
        self._total_requests: int = 0
        self._total_sync_llm_calls: int = 0  # Router + Generator

    def new_request(self, request_id: str) -> PipelineMetrics:
        self._total_requests += 1
        return PipelineMetrics(request_id=request_id)

    def record_sync_llm_call(self) -> None:
        self._total_sync_llm_calls += 1

    def flush(self, m: PipelineMetrics) -> dict:
        """将单次请求的指标落盘/输出"""
        # TODO: 对接 metric 后端（Prometheus / 结构化日志）
        return {
            "request_id": m.request_id,
            "sync_llm_calls": m.router_calls + m.generator_calls,
            "async_llm_calls": m.ingest_calls,
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "latency_total_ms": m.latency_total_ms,
            "tools": f"{m.tools_succeeded}/{m.tools_called} succeeded",
        }

    @property
    def avg_sync_llm_calls_per_request(self) -> float:
        if self._total_requests == 0:
            return 0.0
        return self._total_sync_llm_calls / self._total_requests


# 全局单例
_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics
