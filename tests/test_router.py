"""Router 单元测试：_parse_decision 对小模型脏输出的容错 + abandon_clarify 标志位。"""

from app.agent.router import Router, ROUTER_SCHEMA, RouterDecision


def _router() -> Router:
    return Router.__new__(Router)  # 跳过 __init__，只测解析逻辑


# ── 标准形态 ─────────────────────────────────────────────────

def test_parse_standard():
    d = _router()._parse_decision({
        "intent": "execute",
        "reasoning": "用户要抽牌",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 3}}],
        "clarify_params": {"birth_date": "1995-06-15"},
        "abandon_clarify": False,
    })
    assert d.intent == "execute"
    assert d.reasoning == "用户要抽牌"
    assert len(d.tool_selections) == 1
    assert d.tool_selections[0].tool_id == "tarot_draw"
    assert d.tool_selections[0].params == {"count": 3}
    assert d.clarify_params == {"birth_date": "1995-06-15"}
    assert d.abandon_clarify is False


def test_parse_knowledge_and_explain():
    d = _router()._parse_decision({
        "intent": "knowledge", "knowledge_query": "塔罗的原理",
    })
    assert d.intent == "knowledge" and d.knowledge_query == "塔罗的原理"
    d2 = _router()._parse_decision({
        "intent": "explain", "trace_lookup_index": 2,
    })
    assert d2.intent == "explain" and d2.trace_lookup_index == 2


# ── abandon_clarify 标志位 ────────────────────────────────────

def test_abandon_clarify_true():
    d = _router()._parse_decision({"intent": "execute", "abandon_clarify": True})
    assert d.abandon_clarify is True


def test_abandon_clarify_default_false():
    d = _router()._parse_decision({"intent": "execute"})
    assert d.abandon_clarify is False


def test_abandon_clarify_dirty_values():
    for dirty in ("true", 1, "yes"):
        d = _router()._parse_decision({"intent": "execute", "abandon_clarify": dirty})
        assert d.abandon_clarify is True, f"{dirty!r} 应按真值处理"
    for dirty in ("false", 0, "", None):
        d = _router()._parse_decision({"intent": "execute", "abandon_clarify": dirty})
        assert d.abandon_clarify is False, f"{dirty!r} 应按假值处理"


# ── 小模型脏格式容错（skill 记录的真实事故）──────────────────

def test_parse_string_array():
    """真实事故：tool_selections 返回字符串数组 [\"birth_chart\"]。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": ["birth_chart"],
    })
    assert len(d.tool_selections) == 1
    assert d.tool_selections[0].tool_id == "birth_chart"
    assert d.tool_selections[0].params == {}


def test_parse_dict_value_form():
    """真实事故：dict 值形态 {\"tool1\": \"horoscope_daily\"}。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": {"tool1": "horoscope_daily"},
    })
    assert [t.tool_id for t in d.tool_selections] == ["horoscope_daily"]


def test_parse_dict_key_form():
    """真实事故：dict 键形态 {\"tarot_draw\": {\"count\": 3}}。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": {"tarot_draw": {"count": 3}},
    })
    assert len(d.tool_selections) == 1
    assert d.tool_selections[0].tool_id == "tarot_draw"
    assert d.tool_selections[0].params == {"count": 3}


def test_parse_mixed_forms():
    """同一数组内混字符串和 dict。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": ["tarot_draw", {"tool_id": "birth_chart", "params": {"birth_date": "x"}}],
    })
    assert [t.tool_id for t in d.tool_selections] == ["tarot_draw", "birth_chart"]


def test_parse_parameters_key_alias():
    """真实事故：qwen 输出 \"parameters\" 键而非 \"params\" → 参数必须兼容。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": [{
            "tool_id": "birth_chart",
            "parameters": {"birth_date": "1995-06-15"},
        }],
    })
    assert d.tool_selections[0].params == {"birth_date": "1995-06-15"}


def test_parse_placeholder_key_with_params():
    """真实事故：qwen 输出 {"tool": "horoscope_daily", "params": {"sign": "白羊座"}}
    占位键形态——必须合并为单个有效选择，否则参数丢失→澄清死循环。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": {
            "tool": "horoscope_daily",
            "params": {"sign": "白羊座"},
        },
    })
    assert len(d.tool_selections) == 1
    assert d.tool_selections[0].tool_id == "horoscope_daily"
    assert d.tool_selections[0].params == {"sign": "白羊座"}


def test_parse_placeholder_numeric_keys():
    """占位编号键：{"tool1": "tarot_draw"} → tool_id 是 value。"""
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": {"tool1": "tarot_draw", "tool2": "horoscope_daily"},
    })
    assert [t.tool_id for t in d.tool_selections] == ["tarot_draw", "horoscope_daily"]


def test_parse_missing_tool_id_skipped():
    d = _router()._parse_decision({
        "intent": "execute",
        "tool_selections": [{"params": {}}, "tarot_draw"],
    })
    assert [t.tool_id for t in d.tool_selections] == ["", "tarot_draw"]


def test_parse_non_dict_output():
    """非 dict 顶层输出（裸字符串）→ 安全降级 direct。"""
    d = _router()._parse_decision("direct")
    assert d.intent == "direct"
    assert d.tool_selections == []


def test_parse_intent_missing():
    d = _router()._parse_decision({"tool_selections": []})
    assert d.intent == "direct"  # 缺 intent 默认 direct


# ── Schema 完整性 ─────────────────────────────────────────────

def test_router_schema_has_abandon_clarify():
    props = ROUTER_SCHEMA["properties"]
    assert "abandon_clarify" in props
    assert props["abandon_clarify"]["type"] == "boolean"
    assert "clarify_params" in props
    assert "intent" in ROUTER_SCHEMA["required"]


def test_router_decision_fields_complete():
    import dataclasses
    names = {f.name for f in dataclasses.fields(RouterDecision)}
    assert {"intent", "tool_selections", "clarify_params", "abandon_clarify"} <= names
