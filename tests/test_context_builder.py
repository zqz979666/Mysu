"""ContextBuilder 测试：工具结果文本化、知识片段、token 预算截断。"""

from app.agent.context_builder import ContextBuilder
from app.agent.context_loader import LoadedContext
from app.knowledge.knowledge_retriever import KnowledgeHit
from app.models.domain import ToolResult


def _ctx():
    return LoadedContext(user_profile={"name": "小明", "zodiac_sign": "aries"})


def test_format_success_results():
    text = ContextBuilder()._format_tool_results([
        ToolResult(tool_id="tarot_draw", success=True, output={"cards": 3}),
    ])
    assert "tarot_draw" in text
    assert "✓" in text
    assert "cards" in text


def test_format_failure_results():
    text = ContextBuilder()._format_tool_results([
        ToolResult(tool_id="birth_chart", success=False, error="缺出生日期"),
    ])
    assert "✗" in text
    assert "缺出生日期" in text


def test_format_trace_included():
    text = ContextBuilder()._format_tool_results([
        ToolResult(tool_id="tarot_draw", success=True, output={"x": 1}, trace="执行: tarot_draw(count=1)"),
    ])
    assert "执行记录" in text


def test_no_tool_results():
    text = ContextBuilder()._format_tool_results([])
    assert "本回合未调用工具" in text


def test_knowledge_fragments():
    cb = ContextBuilder()
    text = cb._format_knowledge_hits([
        KnowledgeHit(doc_id="d1", content="塔罗牌共78张", source="system_kb"),
    ])
    assert "塔罗牌共78张" in text
    assert "system_kb" in text


def test_build_with_profile_fragment():
    gc = ContextBuilder().build(
        user_message="帮我看看运势",
        context=_ctx(),
        tool_results=[ToolResult(tool_id="tarot_draw", success=True, output={"cards": [1]})],
    )
    assert gc.user_message == "帮我看看运势"
    assert "小明" in gc.system_prompt_fragment
    assert "tarot_draw" in gc.tool_outputs


def test_build_truncates_huge_tool_output():
    cb = ContextBuilder(max_total_tokens=64)
    gc = cb.build(
        user_message="hi",
        context=LoadedContext(),
        tool_results=[
            ToolResult(tool_id="tarot_draw", success=True,
                       output={"huge": "x" * 5000})
        ],
    )
    assert "(截断)" in gc.tool_outputs


def test_estimate_tokens():
    assert ContextBuilder()._estimate_tokens("abcd") == 1
