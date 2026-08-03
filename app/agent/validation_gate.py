"""
校验闸门——在工具执行前验证 Router 决策的合法性。

两层校验：
1. tool_id 是否在 DomainRegistry 中存在
2. params 是否符合 ToolSpec.schema 的 JSON Schema
"""

from app.domain.domain_registry import DomainRegistry
from app.agent.router import RouterDecision, ToolSelection
from app.models.domain import ToolSpec


class ValidationResult:
    """校验结果"""

    def __init__(self):
        self.valid: list[ToolSelection] = []
        self.invalid: list[tuple[ToolSelection, str]] = []  # (selection, reason)
        self.unknown_tool_ids: list[str] = []

    @property
    def all_valid(self) -> bool:
        return len(self.invalid) == 0 and len(self.unknown_tool_ids) == 0


class ValidationGate:
    """校验闸门。

    面试话术：为什么需要这一层？因为 LLM 可能幻觉——
    选一个不存在的 tool_id，或者填一个不合法的参数。
    校验闸门是确定性防护，不依赖 LLM 的「自觉」。
    """

    def __init__(self, registry: DomainRegistry):
        self.registry = registry

    def validate(self, decision: RouterDecision) -> ValidationResult:
        """校验 Router 决策中的所有 tool_selections。

        Args:
            decision: Router 的输出

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        for selection in decision.tool_selections:
            tool: ToolSpec | None = self.registry.get_tool(selection.tool_id)

            if tool is None:
                result.unknown_tool_ids.append(selection.tool_id)
                result.invalid.append(
                    (selection, f"tool_id '{selection.tool_id}' 未注册")
                )
                continue

            # TODO: 实现 JSON Schema 校验
            # jsonschema.validate(selection.params, tool.schema)
            result.valid.append(selection)

        return result
