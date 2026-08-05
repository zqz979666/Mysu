"""塔罗工具测试：抽牌数量、输出结构、trace、验证逻辑。"""

import pytest

from app.domain_packs.metacare.tarot import TarotDrawTool
from app.models.domain import ExecutionContext


@pytest.fixture
def tool():
    return TarotDrawTool()


@pytest.fixture
def ctx():
    return ExecutionContext(session_id="s1", user_id="u1", request_id="r1")


async def test_draw_one_card(tool, ctx):
    result = await tool.execute({"count": 1}, ctx)
    assert result.success
    assert result.output["count"] == 1
    assert len(result.output["cards"]) == 1
    card = result.output["cards"][0]
    assert card["position"] == "当前"
    assert card["name"] and card["name_en"]
    assert card["orientation"] in ("正位", "逆位")
    assert card["keywords"] and card["meaning"]


async def test_draw_three_cards(tool, ctx):
    result = await tool.execute({"count": 3}, ctx)
    assert result.success
    assert len(result.output["cards"]) == 3
    positions = [c["position"] for c in result.output["cards"]]
    assert positions == ["过去", "现在", "未来"]


async def test_count_defaults_to_one(tool, ctx):
    """count 缺省 → 1 张（澄清闸门绝不触发的原因）。"""
    result = await tool.execute({}, ctx)
    assert result.success
    assert result.output["count"] == 1
    assert len(result.output["cards"]) == 1


async def test_question_passthrough(tool, ctx):
    result = await tool.execute({"count": 1, "question": "我该换工作吗"}, ctx)
    assert result.output["question"] == "我该换工作吗"


async def test_trace_present(tool, ctx):
    result = await tool.execute({"count": 1}, ctx)
    assert "tarot_draw" in result.trace
    assert "随机种子" in result.trace


def test_validate_params_never_clarifies(tool):
    """validate_params 恒返回 []——count 有默认值，缺省即可执行。"""
    assert tool.validate_params({}) == []
    assert tool.validate_params({"count": 3}) == []


async def test_no_duplicate_cards_in_three_draw(tool, ctx):
    """三张牌不重复（从 78 张洗牌取前 3）。"""
    result = await tool.execute({"count": 3}, ctx)
    names = [c["name_en"] for c in result.output["cards"]]
    assert len(set(names)) == 3
