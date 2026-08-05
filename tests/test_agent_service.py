"""AgentService 集成测试——全流程覆盖。

走真实 pipeline（SessionManager → ContextLoader → Router → ValidationGate
→ 画像注入 → 澄清闸门 → ToolExecutor → ContextBuilder → Generator → Ingest），
唯一替换：LLM 走 FakeGateway（真实 LLMClient 逻辑，mock 底层 API）。

覆盖场景：
- execute 全流程（含 2 同步 LLM 调用主张、落库、llm_call_logs）
- direct / knowledge 意图
- execute 无有效工具 → 降级引导
- 澄清全流程：缺参→澄清→回答→resume（pending 生命周期）
- 转话题放弃澄清（abandon_clarify 标志位 + 误填忽略）
- 画像注入跳过澄清
- None 参数清洗
"""

import asyncio

import pytest


# ── execute 全流程 ──────────────────────────────────────────

async def test_execute_full_pipeline(agent_service, fake_gateway, chat_request):
    fake_gateway.set_router({
        "intent": "execute",
        "reasoning": "用户要抽牌",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 3}}],
    })
    fake_gateway.set_generator("你抽到的三张牌是：过去-权杖三、现在-圣杯骑士、未来-星星。")
    fake_gateway.set_ingest({})

    resp = await agent_service.handle_chat(chat_request("帮我抽三张塔罗牌看看"))

    assert resp.intent == "execute"
    assert resp.tool_calls == ["tarot_draw"]
    assert resp.reply == "你抽到的三张牌是：过去-权杖三、现在-圣杯骑士、未来-星星。"

    # 2 个同步 LLM 调用（router + generator），ingest 异步
    assert len(fake_gateway.router_calls) == 1
    assert len(fake_gateway.generator_calls) == 1
    assert len(fake_gateway.ingest_calls) == 0  # 异步，尚未跑

    await fake_gateway.wait_async_calls()
    assert len(fake_gateway.ingest_calls) == 1  # 异步 ingest 完成

    # 落库：L2 readings + L3 session_state
    readings = await agent_service.memory.get_recent_readings("default")
    assert readings and readings[0]["tool_id"] == "tarot_draw"
    state = await agent_service.memory.get_session_state("test-session")
    assert [s["role"] for s in state] == ["user", "assistant"]


async def test_execute_llm_call_logs_persisted(agent_service, fake_gateway, chat_request):
    """llm_call_logs 落 3 条（router/generator/ingest），response 全文。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("一张牌：太阳。")
    await agent_service.handle_chat(chat_request("抽一张牌"))
    await fake_gateway.wait_async_calls()

    from app.storage.database import db_fetch_all
    rows = await db_fetch_all(
        "SELECT call_type, length(response_snippet) as rlen, success "
        "FROM llm_call_logs ORDER BY id", _log=False,
    )
    types = sorted(r["call_type"] for r in rows)
    assert types == ["generator", "ingest", "router"]
    assert all(r["success"] == 1 for r in rows)
    assert all(r["rlen"] > 0 for r in rows)  # 完整落表


# ── direct / knowledge ──────────────────────────────────────

async def test_direct_intent(agent_service, fake_gateway, chat_request):
    fake_gateway.set_router({
        "intent": "direct", "response_direct": "你好呀，我是 Mysu～"
    })
    resp = await agent_service.handle_chat(chat_request("你好"))
    assert resp.intent == "direct"
    assert resp.reply == "你好呀，我是 Mysu～"
    assert resp.tool_calls in (None, [])  # direct 分支不构造 tool_calls


async def test_knowledge_intent(agent_service, fake_gateway, chat_request):
    fake_gateway.set_router({
        "intent": "knowledge", "knowledge_query": "塔罗的原理是什么",
    })
    fake_gateway.set_generator("塔罗的原理是基于荣格共时性理论…")
    resp = await agent_service.handle_chat(chat_request("塔罗的原理是什么？"))
    assert resp.intent == "knowledge"
    # Generator 的 user_prompt 应包含知识检索片段
    gen_prompt = fake_gateway.generator_calls[0]["messages"][1]["content"]
    assert "知识库占位" in gen_prompt


# ── execute 无有效工具降级 ─────────────────────────────────

async def test_execute_no_valid_tool_degrades(agent_service, fake_gateway, chat_request):
    """LLM 幻觉出未注册工具 → 引导用户，不静默 no-op。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "ghost_tool", "params": {}}],
    })
    resp = await agent_service.handle_chat(chat_request("给我算算"))
    assert resp.intent == "direct"
    assert "塔罗" in resp.reply


# ── 澄清全流程 ──────────────────────────────────────────────

async def test_clarification_full_cycle(agent_service, fake_gateway, chat_request):
    # 第一步：问运势（画像为空）→ 澄清闸门触发
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    resp1 = await agent_service.handle_chat(chat_request("看看我今天的运势"))
    assert resp1.intent == "clarification"
    assert resp1.clarification == ["sign 或 birth_date"]
    assert "星座" in resp1.reply
    # pending 已建立
    pending = await agent_service.memory.get_pending_clarification("test-session")
    assert pending is not None
    assert pending["tool_id"] == "horoscope_daily"

    # 第二步：回答生日 → Router 提取 clarify_params → resume 原工具
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
        "clarify_params": {"birth_date": "1995-06-15"},
        "abandon_clarify": False,
    })
    fake_gateway.set_generator("双子座今日运势：整体⭐⭐…")
    fake_gateway.set_ingest({"birth_date": "1995-06-15"})
    resp2 = await agent_service.handle_chat(chat_request("我是1995年6月15日出生的"))
    assert resp2.intent == "execute"
    assert resp2.tool_calls == ["horoscope_daily"]
    # pending 已清除
    assert await agent_service.memory.get_pending_clarification("test-session") is None

    # 画像异步落库
    await fake_gateway.wait_async_calls()
    profile = await agent_service.memory.get_profile("default")
    assert profile.birth_date == "1995-06-15"


async def test_clarification_pending_not_created_without_profile_fk_error(
    agent_service, fake_gateway, chat_request,
):
    """FK 前置：_ensure_profile 必须先于 set_pending_clarification（历史事故）。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "birth_chart", "params": {}}],
    })
    resp = await agent_service.handle_chat(chat_request("帮我看看星盘"))
    assert resp.intent == "clarification"
    assert resp.clarification == ["birth_date"]
    pending = await agent_service.memory.get_pending_clarification("test-session")
    assert pending["tool_id"] == "birth_chart"  # 未因 FK 崩溃


# ── 转话题放弃澄清（核心修复点）───────────────────────────

async def test_topic_switch_abandons_clarification(agent_service, fake_gateway, chat_request):
    # 第一步：建立 pending
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    resp1 = await agent_service.handle_chat(chat_request("看看我今天的运势"))
    assert resp1.intent == "clarification"

    # 第二步：转话题（即使模型误填 clarify_params，标志位优先放弃）
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 3}}],
        "clarify_params": {"birth_date": "2020-01-01"},  # 误填
        "abandon_clarify": True,
    })
    fake_gateway.set_generator("三张牌已抽好。")
    fake_gateway.set_ingest({})  # 画像不落库
    resp2 = await agent_service.handle_chat(chat_request("帮我抽三张塔罗牌看看"))
    assert resp2.intent == "execute"
    assert resp2.tool_calls == ["tarot_draw"]
    # pending 被清除，误填参数被忽略
    assert await agent_service.memory.get_pending_clarification("test-session") is None
    await fake_gateway.wait_async_calls()
    profile = await agent_service.memory.get_profile("default")
    assert profile.birth_date == ""  # 误填的 2020-01-01 没有污染画像


async def test_reclarify_after_abandon(agent_service, fake_gateway, chat_request):
    """转话题放弃后回到原话题 → 重新澄清（pending 已丢、画像仍空）。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    await agent_service.handle_chat(chat_request("看看我今天的运势"))
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
        "abandon_clarify": True,
    })
    fake_gateway.set_generator("一张牌。")
    await agent_service.handle_chat(chat_request("抽张牌吧"))
    await fake_gateway.wait_async_calls()

    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    resp = await agent_service.handle_chat(chat_request("那再看看运势呢"))
    assert resp.intent == "clarification"
    assert resp.clarification == ["sign 或 birth_date"]


async def test_no_signal_treated_as_topic_switch(agent_service, fake_gateway, chat_request):
    """LLM 既没填 clarify_params 也没标 abandon → 放弃 pending（不困住用户）。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    await agent_service.handle_chat(chat_request("看看我今天的运势"))
    assert await agent_service.memory.get_pending_clarification("test-session") is not None

    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("抽好了。")
    resp = await agent_service.handle_chat(chat_request("换个话题，抽张牌"))
    assert resp.intent == "execute"
    assert resp.tool_calls == ["tarot_draw"]
    assert await agent_service.memory.get_pending_clarification("test-session") is None


# ── 画像注入 / 参数清洗 ────────────────────────────────────

async def test_profile_injection_skips_clarification(agent_service, fake_gateway, chat_request):
    """画像已有 birth_date → 问运势直接执行（注入，不澄清）。"""
    await agent_service.memory.update_profile("default", {"birth_date": "1995-06-15"})
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "horoscope_daily", "params": {}}],
    })
    fake_gateway.set_generator("你的个性化运势来了。")
    resp = await agent_service.handle_chat(chat_request("看看我今天的运势"))
    assert resp.intent == "execute"
    assert resp.tool_calls == ["horoscope_daily"]
    assert resp.clarification is None


async def test_none_params_stripped(agent_service, fake_gateway, chat_request):
    """Router 返回 params 含 None（{"birth_time": None}）→ 清洗后不炸。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{
            "tool_id": "birth_chart",
            "params": {"birth_date": "1995-06-15", "birth_time": None},
        }],
    })
    fake_gateway.set_generator("星盘已生成。")
    resp = await agent_service.handle_chat(chat_request("看星盘，1995年6月15日生"))
    assert resp.intent == "execute"
    assert resp.tool_calls == ["birth_chart"]


async def test_generator_gets_tool_output(agent_service, fake_gateway, chat_request):
    """Generator 的 prompt 应包含工具执行结果（文本化）。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("这是太阳牌。")
    await agent_service.handle_chat(chat_request("抽一张牌"))
    gen_prompt = fake_gateway.generator_calls[0]["messages"][1]["content"]
    assert "工具执行结果" in gen_prompt
    assert "tarot_draw" in gen_prompt


# ── 会话切换 → 自动触发旧会话记忆提炼 ─────────────────────

async def test_session_switch_triggers_memory_extraction(
    agent_service, fake_gateway, chat_request,
):
    """用户开新会话 → 旧会话的对话被全量提炼（画像/事实落库）。"""
    # 会话 A：用户替朋友问（信息不进用户画像的即时提取路径）
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("好的。")
    fake_gateway.set_ingest({})  # 即时提取：他人信息不落库
    await agent_service.handle_chat(chat_request("帮我算下我朋友的运势，他是白羊座", "session-a"))
    await fake_gateway.wait_async_calls()  # 等旧会话的 session_state 落库（提炼依赖）

    # 会话 B：用户开新会话（session-a 结束 → 触发提炼）
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_memory_extract({
        "profile": {"zodiac_sign": "gemini"},
        "facts": [{"type": "relationship", "content": "朋友是白羊座"}],
        "preferences": {},
    })
    await agent_service.handle_chat(chat_request("抽张牌", "session-b"))
    await fake_gateway.wait_for_call_type("记忆提炼器")
    await asyncio.sleep(0.05)  # 等提炼结果落库完成

    # 提炼被触发且落库：画像=双子（用户自述过的），朋友白羊座只进 facts
    assert len(fake_gateway.memory_extract_calls) >= 1
    profile = await agent_service.memory.get_profile("default")
    assert profile.zodiac_sign == "gemini"
    facts = await agent_service.memory.get_facts("default")
    assert any(f["content"] == "朋友是白羊座" for f in facts)

    # 幂等：已提炼的会话（session-a）不重复提炼；新结束的 session-b 会被提炼一次
    calls_before = len(fake_gateway.calls)
    extract_before = len(fake_gateway.memory_extract_calls)
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("好。")
    await agent_service.handle_chat(chat_request("再抽一张", "session-c"))
    # 等 C 的异步 ingest（信息提取器第 3 次）与 session-b 的提炼都完成
    await fake_gateway.wait_for_call_type_count("记忆提炼器", extract_before + 1)
    await fake_gateway.wait_for_call_type_count("信息提取器", 3)
    # session-c 请求本身 3 次调用（router+generator+ingest）+ 提炼 session-b 1 次
    assert len(fake_gateway.calls) == calls_before + 4
    assert len(fake_gateway.memory_extract_calls) == extract_before + 1


async def test_same_session_no_extraction_trigger(agent_service, fake_gateway, chat_request):
    """同一 session 连续请求 → 不触发提炼。"""
    fake_gateway.set_router({
        "intent": "execute",
        "tool_selections": [{"tool_id": "tarot_draw", "params": {"count": 1}}],
    })
    fake_gateway.set_generator("好。")
    await agent_service.handle_chat(chat_request("抽一张", "session-x"))
    await agent_service.handle_chat(chat_request("再抽一张", "session-x"))
    await fake_gateway.wait_async_calls()
    assert len(fake_gateway.memory_extract_calls) == 0
