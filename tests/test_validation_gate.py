"""ValidationGate 单元测试：tool_id 存在性校验（LLM 幻觉防护）。"""

import pytest

from app.agent.router import RouterDecision, ToolSelection
from app.agent.validation_gate import ValidationGate
from app.models.domain import ToolSpec, ToolResult


class FakeTool(ToolSpec):
    async def execute(self, params, ctx):
        return ToolResult(tool_id=self.tool_id, success=True)


@pytest.fixture
def gate():
    from app.domain.domain_registry import DomainRegistry
    registry = DomainRegistry()
    registry._tool_index = {
        "tarot_draw": FakeTool("tarot_draw", "塔罗", "塔罗牌",
                               {"type": "object", "properties": {}, "required": []}),
    }
    return ValidationGate(registry)


def test_valid_tool_passes(gate):
    decision = RouterDecision(
        intent="execute",
        tool_selections=[ToolSelection("tarot_draw", {"count": 3})],
    )
    result = gate.validate(decision)
    assert result.all_valid
    assert len(result.valid) == 1
    assert result.valid[0].tool_id == "tarot_draw"
    assert result.invalid == []
    assert result.unknown_tool_ids == []


def test_unknown_tool_rejected(gate):
    decision = RouterDecision(
        intent="execute",
        tool_selections=[
            ToolSelection("tarot_draw", {}),
            ToolSelection("ghost_tool", {}),  # LLM 幻觉
        ],
    )
    result = gate.validate(decision)
    assert not result.all_valid
    assert len(result.valid) == 1
    assert result.unknown_tool_ids == ["ghost_tool"]
    assert len(result.invalid) == 1
    assert "未注册" in result.invalid[0][1]


def test_empty_selections(gate):
    result = gate.validate(RouterDecision(intent="direct"))
    assert result.all_valid
    assert result.valid == []
