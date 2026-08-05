"""ProfileExtractor 测试：LLM 全权判断 + 防御性值校验 + 澄清动态 schema。"""

import pytest

from app.memory.profile_extractor import (
    ProfileExtractor,
    extract_clarify_params,
    _build_clarify_schema,
)


# ── 防御性值校验（不参与判断，只拒绝垃圾值）──────────────

async def test_llm_garbage_values_filtered(tmp_db_path, fake_gateway):
    """LLM 吐出垃圾值（?、我是）→ 过滤，不污染画像。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    fake_gateway.set_ingest({
        "birth_date": "? ??",
        "birth_time": "??:??",
        "name": "我是",
        "zodiac_sign": "aries",
    })
    await memory.ingest("s1", "u1", {
        "user_message": "我是白羊座",
        "assistant_reply": "好",
        "intent": "execute",
        "tool_results": [],
    })
    await fake_gateway.wait_async_calls()
    p = await memory.get_profile("u1")
    assert p.birth_date == ""       # 垃圾日期被拒
    assert p.birth_time == ""       # 垃圾时间被拒
    assert p.name == ""             # 无意义名字被拒
    assert p.zodiac_sign == "aries"  # 合法值保留


async def test_extract_returns_empty_on_no_llm_output(fake_gateway):
    extractor = ProfileExtractor(fake_gateway.client)
    fake_gateway.set_ingest({})
    result = await extractor.extract("看看白羊座运势")
    assert result == {}


async def test_extract_third_person_rejected(fake_gateway):
    """替他人转述（他/我朋友）→ 即时提取绝不写用户画像（USER-DIRECTED）。"""
    extractor = ProfileExtractor(fake_gateway.client)
    fake_gateway.set_ingest({})  # LLM 判断为他人信息
    for msg in ["他是白羊座", "帮我朋友算下运势，他是白羊座", "我朋友是双子座"]:
        result = await extractor.extract(msg)
        assert result == {}, f"{msg} 不应提取到用户画像"


async def test_extract_self_statement_kept(fake_gateway):
    """强自指（我是/我的）仍即时提取。"""
    extractor = ProfileExtractor(fake_gateway.client)
    fake_gateway.set_ingest({"birth_date": "1995-06-15", "zodiac_sign": "gemini"})
    result = await extractor.extract("我是1995年6月15日出生的双子座")
    assert result["birth_date"] == "1995-06-15"
    assert result["zodiac_sign"] == "gemini"


# ── 会话级记忆提炼（session 结束后全量判断）──────────────

async def test_extract_session_memory_parse(fake_gateway):
    from app.memory.profile_extractor import extract_session_memory
    fake_gateway.set_memory_extract({
        "profile": {"birth_date": "1995-06-15", "zodiac_sign": "aries"},
        "facts": [
            {"type": "preference", "content": "喜欢猫"},
            {"type": "relationship", "content": "朋友是白羊座"},
        ],
        "preferences": {"reply_style": "简洁"},
    })
    out = await extract_session_memory(fake_gateway.client, "[用户] 我是白羊座\n[助手] 好的")
    assert out["profile"]["zodiac_sign"] == "aries"
    assert len(out["facts"]) == 2
    assert out["preferences"] == {"reply_style": "简洁"}
    # call_type 落 memory_extract
    assert any("记忆提炼器" in c["messages"][0]["content"] for c in fake_gateway.calls)


async def test_extract_session_memory_value_validation(fake_gateway):
    """防御性校验：垃圾日期/无意义名字被过滤，但 fact 保留。"""
    from app.memory.profile_extractor import extract_session_memory
    fake_gateway.set_memory_extract({
        "profile": {"birth_date": "? ??", "name": "我是", "gender": "male"},
        "facts": [{"type": "life_event", "content": "最近在找工作"}],
        "preferences": {},
    })
    out = await extract_session_memory(fake_gateway.client, "[用户] 我最近在找工作")
    assert out["profile"] == {"gender": "male"}  # 垃圾值被过滤
    assert len(out["facts"]) == 1
    assert out["facts"][0]["content"] == "最近在找工作"


async def test_extract_session_memory_bad_facts_dropped(fake_gateway):
    from app.memory.profile_extractor import extract_session_memory
    fake_gateway.set_memory_extract({
        "profile": {},
        "facts": [
            {"type": "hack", "content": "非法类型"},
            {"type": "preference", "content": "x"},  # 内容过短
            {"type": "relationship", "content": "有个妹妹在读大学"},
        ],
        "preferences": "not-a-dict",
    })
    out = await extract_session_memory(fake_gateway.client, "[用户] 我有个妹妹")
    assert out["facts"] == [{"type": "relationship", "content": "有个妹妹在读大学"}]
    assert out["preferences"] == {}


# ── 澄清动态 schema ─────────────────────────────────────────

def test_build_clarify_schema_splits_or():
    schema = _build_clarify_schema(["sign 或 birth_date"])
    assert set(schema["properties"].keys()) == {"sign", "birth_date"}


def test_build_clarify_schema_cleans_prefix():
    schema = _build_clarify_schema(["缺少参数: question"])
    assert set(schema["properties"].keys()) == {"question"}


def test_build_clarify_schema_empty():
    assert _build_clarify_schema([]) == {"type": "object", "properties": {}}


async def test_extract_clarify_params_dynamic(fake_gateway):
    """澄清提取按缺失字段动态解析（与画像提取解耦）。"""
    fake_gateway.set_router({"sign": "aries", "partner_name": "小红"})
    # router_script 被 clarify 提取复用——直接构造 LLM 返回更精确：
    # 用 call_type=clarify 分支：FakeGateway 目前按 system prompt 分发，
    # 澄清提取的 system prompt 是"你是一个参数提取器"
    from app.llm.llm_client import LLMClient, LLMCallConfig, LLMCallResult
    import json

    async def clarify_create(**kwargs):
        return type("R", (), {
            "choices": [type("C", (), {"message": type("M", (), {"content": json.dumps({"sign": "aries", "partner_name": "小红"})})()})()],
            "usage": type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})(),
        })()

    import types
    fake_gateway.client._clients["fake"].chat = types.SimpleNamespace(
        completions=types.SimpleNamespace(create=clarify_create)
    )
    result = await extract_clarify_params(
        fake_gateway.client, "我是白羊座，女朋友叫小红", ["sign", "partner_name"]
    )
    assert result.get("sign") == "aries"
    assert result.get("partner_name") == "小红"


async def test_extract_clarify_params_unknown_fields_dropped(fake_gateway):
    """LLM 返回 schema 外的字段 → 丢弃。"""
    from app.llm.llm_client import LLMCallConfig, LLMCallResult
    import json, types

    async def clarify_create(**kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({"sign": "aries", "hack": "x"})))],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    fake_gateway.client._clients["fake"].chat = types.SimpleNamespace(
        completions=types.SimpleNamespace(create=clarify_create)
    )
    result = await extract_clarify_params(fake_gateway.client, "我是白羊座", ["sign"])
    assert result == {"sign": "aries"}
