"""
工具执行器——并行执行 + 失败隔离。

关键设计：
- 并行执行：同一轮选中的多个工具并发跑（asyncio.gather）
- 失败隔离：一个工具 fail 不影响其他工具执行
- 超时控制：每个工具独立超时
- 结果收集：按 tool_id 索引返回

面试话术：并行执行 + 失败隔离 是生产级工具调用和 demo 的本质区别。
demo 串行执行，一个工具崩了整个请求 500。
这里每个工具有独立超时和错误边界，一个 fail 其他继续跑，
Generator 拿到 partial results 也能给出合理回复（"塔罗结果出来了，排盘暂时不可用"）。
"""

import asyncio
from app.models.domain import ExecutionContext, ToolResult
from app.domain.domain_registry import DomainRegistry
from app.observability.logger import logger


# 单工具超时（秒）
DEFAULT_TOOL_TIMEOUT = 30


class ToolExecutor:
    """并行工具执行器。

    职责：
    1. 并行调度多个工具执行
    2. 独立超时和失败隔离
    3. 收集成功/失败结果
    """

    def __init__(self, registry: DomainRegistry):
        self.registry = registry

    async def execute(
        self,
        tool_ids_and_params: list[tuple[str, dict]],
        ctx: ExecutionContext,
    ) -> list[ToolResult]:
        """并行执行多个工具。

        Args:
            tool_ids_and_params: [(tool_id, params), ...]
            ctx: 执行上下文

        Returns:
            每个工具的执行结果（顺序与输入一致）
        """
        tasks = []
        for tool_id, params in tool_ids_and_params:
            tasks.append(self._execute_one(tool_id, params, ctx))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统一异常处理：将 Exception 转为 ToolResult
        resolved: list[ToolResult] = []
        for i, r in enumerate(results):
            tool_id = tool_ids_and_params[i][0]
            if isinstance(r, Exception):
                resolved.append(
                    ToolResult(
                        tool_id=tool_id,
                        success=False,
                        error=f"执行异常: {str(r)}",
                    )
                )
            else:
                resolved.append(r)

        return resolved

    async def _execute_one(
        self, tool_id: str, params: dict, ctx: ExecutionContext
    ) -> ToolResult:
        """执行单个工具（带超时 + 错误隔离）"""
        tool = self.registry.get_tool(tool_id)
        if tool is None:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"工具 '{tool_id}' 未注册",
            )

        try:
            result = await asyncio.wait_for(
                tool.execute(params, ctx),
                timeout=DEFAULT_TOOL_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"工具执行超时（{DEFAULT_TOOL_TIMEOUT}s）",
            )
        except Exception as e:
            logger.exception(f"工具 {tool_id} 执行失败")
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(e),
            )
