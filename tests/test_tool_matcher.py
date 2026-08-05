"""ToolMatcher 单元测试：确定性候选召回。"""

import pytest

from app.agent.tool_matcher import ToolMatcher
from app.models.domain import ToolSpec, ToolResult, ExecutionContext


class FakeTool(ToolSpec):
    def __init__(self, tool_id, display_name, description, schema=None):
        super().__init__(tool_id, display_name, description, schema or {"type": "object", "properties": {}, "required": []})

    async def execute(self, params, ctx):
        return ToolResult(tool_id=self.tool_id, success=True)


@pytest.fixture
def matcher():
    m = ToolMatcher(top_k=10)
    tools = [
        FakeTool("tarot_draw", "塔罗抽牌", "随机抽取塔罗牌、占卜、抽牌、牌阵"),
        FakeTool("birth_chart", "本命星盘", "出生星盘、排盘、行星位置"),
        FakeTool("horoscope_daily", "每日星座运势", "星座运势、今日运势、财运"),
    ]
    return m, tools


async def test_exact_tool_id_match(matcher):
    m, tools = matcher
    await m.rebuild_index(tools)
    cands = await m.match("帮我用 tarot_draw")
    assert "tarot_draw" in cands


async def test_display_name_match(matcher):
    m, tools = matcher
    await m.rebuild_index(tools)
    cands = await m.match("看看我的本命星盘")
    assert "birth_chart" in cands


async def test_single_alias(matcher):
    m, tools = matcher
    m.add_alias("抽一张", "tarot_draw")
    await m.rebuild_index(tools)
    cands = await m.match("给我抽一张")
    assert "tarot_draw" in cands


async def test_multi_value_alias_topic(matcher):
    """主题词（财运）→ 多工具候选列表。"""
    m, tools = matcher
    m.add_aliases({"财运": ["horoscope_daily", "tarot_draw"]})
    await m.rebuild_index(tools)
    cands = await m.match("我财运如何")
    assert "horoscope_daily" in cands
    assert "tarot_draw" in cands


async def test_keyword_fallback(matcher):
    """description 关键词命中（无别名无精确）。"""
    m, tools = matcher
    await m.rebuild_index(tools)
    cands = await m.match("帮我占卜一下")
    assert "tarot_draw" in cands


async def test_no_match_returns_all(matcher):
    m, tools = matcher
    await m.rebuild_index(tools)
    cands = await m.match("今天天气怎么样")
    assert set(cands) == {t.tool_id for t in tools}


async def test_top_k_truncation():
    m = ToolMatcher(top_k=2)
    tools = [FakeTool(f"tool_{i}", f"工具{i}", f"描述{i}") for i in range(5)]
    await m.rebuild_index(tools)
    cands = await m.match("完全不相关的话")
    assert len(cands) <= 2


async def test_no_duplicates(matcher):
    m, tools = matcher
    m.add_alias("占卜", "tarot_draw")
    await m.rebuild_index(tools)
    cands = await m.match("塔罗抽牌占卜")
    assert cands.count("tarot_draw") == 1


async def test_get_tool_summary(matcher):
    m, tools = matcher
    # get_tool_summary 依赖索引（生产路径在 rebuild_index 之后调用）
    await m.rebuild_index(tools)
    summary = m.get_tool_summary(["tarot_draw"])
    assert "tarot_draw" in summary
    assert "塔罗抽牌" in summary


def test_get_tool_summary_empty():
    m = ToolMatcher()
    assert m.get_tool_summary(["ghost"]) == "[无可用工具]"
