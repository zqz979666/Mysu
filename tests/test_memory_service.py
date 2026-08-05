"""MemoryService 测试：四层记忆 CRUD + 待澄清状态 + 画像提取。"""

import json

import pytest


# ── L0 画像 ─────────────────────────────────────────────────

async def test_get_profile_empty(memory_service):
    p = await memory_service.get_profile("u1")
    assert p.is_empty


async def test_update_and_read_profile(memory_service):
    await memory_service.update_profile("u1", {
        "birth_date": "1995-06-15",
        "birth_time": "14:30",
        "zodiac_sign": "gemini",
        "name": "小明",
        "preferences": {"theme": "dark"},
    })
    p = await memory_service.get_profile("u1")
    assert p.birth_date == "1995-06-15"
    assert p.birth_time == "14:30"
    assert p.zodiac_sign == "gemini"
    assert p.name == "小明"
    assert p.preferences == {"theme": "dark"}
    assert not p.is_empty
    assert "出生日期=1995-06-15" in p.summary()


# ── L1/L2/L3 ────────────────────────────────────────────────

async def test_add_and_get_facts(memory_service):
    await memory_service._ensure_profile("u1")
    await memory_service.add_fact("u1", "preference", "喜欢猫", session_id="s1")
    facts = await memory_service.get_facts("u1")
    assert facts and facts[0]["content"] == "喜欢猫"


async def test_readings_and_session_state(memory_service):
    await memory_service._ensure_profile("u1")
    await memory_service.ingest("s1", "u1", {
        "user_message": "帮我抽牌",
        "assistant_reply": "这是你的牌",
        "intent": "execute",
        "tool_results": [{"tool_id": "tarot_draw", "success": True}],
    })
    readings = await memory_service.get_recent_readings("u1")
    assert readings and readings[0]["tool_id"] == "tarot_draw"
    state = await memory_service.get_session_state("s1")
    assert [s["role"] for s in state] == ["user", "assistant"]


# ── 待澄清状态 ─────────────────────────────────────────────

async def test_pending_clarification_set_get_clear(memory_service):
    await memory_service._ensure_profile("u1")  # FK 前置
    await memory_service.set_pending_clarification(
        "s1", "u1", "horoscope_daily", ["sign 或 birth_date"], "你的星座是？"
    )
    pending = await memory_service.get_pending_clarification("s1")
    assert pending["tool_id"] == "horoscope_daily"
    assert pending["missing_params"] == ["sign 或 birth_date"]
    assert pending["partial_params"] == {}
    assert pending["ask_message"] == "你的星座是？"

    await memory_service.clear_pending_clarification("s1")
    assert await memory_service.get_pending_clarification("s1") is None


async def test_pending_multi_round_accumulation(memory_service):
    await memory_service._ensure_profile("u1")
    await memory_service.set_pending_clarification(
        "s1", "u1", "birth_chart", ["birth_date", "birth_time"], "生日？"
    )
    await memory_service.update_pending_clarification(
        "s1", ["birth_time"], {"birth_date": "1995-06-15"}, "还差时间？"
    )
    pending = await memory_service.get_pending_clarification("s1")
    assert pending["missing_params"] == ["birth_time"]
    assert pending["partial_params"] == {"birth_date": "1995-06-15"}


async def test_pending_upsert_overwrites(memory_service):
    """同 session 重复 set → 覆盖旧值（ON CONFLICT DO UPDATE）。"""
    await memory_service._ensure_profile("u1")
    await memory_service.set_pending_clarification("s1", "u1", "tool_a", ["x"], "q1")
    await memory_service.set_pending_clarification("s1", "u1", "tool_b", ["y"], "q2")
    pending = await memory_service.get_pending_clarification("s1")
    assert pending["tool_id"] == "tool_b"
    assert pending["missing_params"] == ["y"]


# ── Regex 画像提取（LLM 不可用兜底）───────────────────────

def test_regex_self_statement_extracts():
    from app.memory.memory_service import _extract_profile_hints
    hints = _extract_profile_hints("我是1995年6月15日出生的")
    assert hints.get("birth_date") == "1995-06-15"


def test_regex_time_parsing():
    from app.memory.memory_service import _extract_profile_hints, _parse_birth_time
    assert _parse_birth_time("下午2点半") == "14:30"
    assert _parse_birth_time("早上8点") == "08:00"
    assert _parse_birth_time("晚上9点15分") == "21:15"
    assert _parse_birth_time("14:30") == "14:30"
    assert _parse_birth_time("没有时间") is None
    hints = _extract_profile_hints("我是白羊座，1995年6月15日出生，下午2点半生的")
    assert hints["birth_date"] == "1995-06-15"
    assert hints["birth_time"] == "14:30"
    assert hints["zodiac_sign"] == "aries"


def test_regex_non_self_reference_rejected():
    """打听他人信息 → 不提取。"""
    from app.memory.memory_service import _extract_profile_hints
    assert _extract_profile_hints("看看白羊座今天的运势") == {}
    assert _extract_profile_hints("我朋友是双子座") == {}


# ── LLM 画像提取路径（ingest 全流程）───────────────────────

async def test_ingest_with_llm_extraction(tmp_db_path, fake_gateway):
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    fake_gateway.set_ingest({"birth_date": "1995-06-15", "zodiac_sign": "gemini"})

    await memory.ingest("s1", "u1", {
        "user_message": "我是1995年6月15日出生的双子座",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    await fake_gateway.wait_async_calls()

    p = await memory.get_profile("u1")
    assert p.birth_date == "1995-06-15"
    assert p.zodiac_sign == "gemini"
    # 画像提取走 LLM（call_type=ingest），不是 regex
    assert len(fake_gateway.ingest_calls) == 1


async def test_ingest_llm_extraction_empty_keeps_profile_clean(tmp_db_path, fake_gateway):
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    fake_gateway.set_ingest({})  # LLM 判断无个人信息
    await memory.ingest("s1", "u1", {
        "user_message": "看看白羊座今天的运势",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    await fake_gateway.wait_async_calls()
    p = await memory.get_profile("u1")
    assert p.is_empty


async def test_ingest_third_person_never_pollutes_profile(tmp_db_path, fake_gateway):
    """用户替他人询问（"帮我朋友算，他是白羊座"）→ 画像绝不被污染（USER-DIRECTED）。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    fake_gateway.set_ingest({})  # LLM 判断：白羊座是朋友的，不是用户的
    await memory.ingest("s1", "u1", {
        "user_message": "帮我算下我朋友的运势，他是白羊座",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    await fake_gateway.wait_async_calls()
    p = await memory.get_profile("u1")
    assert p.zodiac_sign == ""  # 未被污染
    assert p.is_empty


async def test_ingest_self_statement_updates_profile(tmp_db_path, fake_gateway):
    """强自指仍即时落库（双轨的即时性）。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    fake_gateway.set_ingest({"birth_date": "1995-06-15"})
    await memory.ingest("s1", "u1", {
        "user_message": "我是1995年6月15日出生的",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    await fake_gateway.wait_async_calls()
    p = await memory.get_profile("u1")
    assert p.birth_date == "1995-06-15"


# ── 会话级记忆提炼（session 结束后全量判断）──────────────

async def test_extract_session_memory_full_flow(tmp_db_path, fake_gateway):
    """全量对话 → LLM 提炼 → 画像/事实/偏好落库 + 幂等标记。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)

    # 造一段对话（含他人信息 + 自述 + 偏好）
    for i, (role, content) in enumerate([
        ("user", "帮我算下我朋友的运势，他是白羊座"),
        ("assistant", "好的，白羊座的朋友今日运势…"),
        ("user", "顺便说下，我是1995年6月15日出生的双子座"),
        ("assistant", "记下了，你的星盘是双子座"),
    ]):
        await memory.ingest("s_old", "u1", {
            "user_message" if role == "user" else "assistant_reply": content,
            "intent": "execute",
            "tool_results": [],
        })

    fake_gateway.set_memory_extract({
        "profile": {"birth_date": "1995-06-15", "zodiac_sign": "gemini"},
        "facts": [
            {"type": "relationship", "content": "朋友是白羊座"},
            {"type": "preference", "content": "喜欢猫"},
        ],
        "preferences": {"reply_style": "简洁"},
    })
    ok = await memory.extract_session_memory("s_old", "u1")
    assert ok is True

    p = await memory.get_profile("u1")
    assert p.birth_date == "1995-06-15"
    assert p.zodiac_sign == "gemini"
    assert p.preferences == {"reply_style": "简洁"}

    facts = await memory.get_facts("u1")
    contents = {f["content"] for f in facts}
    assert "朋友是白羊座" in contents
    assert "喜欢猫" in contents

    # 幂等：二次提炼直接跳过（不重复 LLM 调用）
    calls_before = len(fake_gateway.calls)
    ok2 = await memory.extract_session_memory("s_old", "u1")
    assert ok2 is False
    assert len(fake_gateway.calls) == calls_before


async def test_extract_session_memory_third_person_not_in_profile(tmp_db_path, fake_gateway):
    """提炼输出即使含他人信息，也只会进 facts（relationship），不进 profile。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    await memory.ingest("s1", "u1", {
        "user_message": "帮我朋友看看，他是白羊座",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    # LLM 正确判断：profile 不含白羊座，白羊座作为 relationship fact
    fake_gateway.set_memory_extract({
        "profile": {},
        "facts": [{"type": "relationship", "content": "朋友是白羊座"}],
        "preferences": {},
    })
    ok = await memory.extract_session_memory("s1", "u1")
    assert ok is True
    p = await memory.get_profile("u1")
    assert p.zodiac_sign == ""  # 白羊座没有进用户画像
    facts = await memory.get_facts("u1")
    assert facts and facts[0]["content"] == "朋友是白羊座"


async def test_extract_session_memory_empty_session(tmp_db_path, fake_gateway):
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=fake_gateway.client)
    ok = await memory.extract_session_memory("no_such_session", "u1")
    assert ok is False  # 无对话内容，不提炼


async def test_extract_session_memory_no_llm(tmp_db_path):
    """无 LLM 配置（regex 兜底模式）→ 会话级提炼跳过。"""
    from app.memory.memory_service import MemoryService
    memory = MemoryService(db_path=tmp_db_path, llm_client=None)
    await memory.ingest("s1", "u1", {
        "user_message": "我是白羊座",
        "assistant_reply": "好的",
        "intent": "execute",
        "tool_results": [],
    })
    ok = await memory.extract_session_memory("s1", "u1")
    assert ok is False
