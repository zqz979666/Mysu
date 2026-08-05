"""LLMClient 测试：schema 回显检测、重试、全文落表、JSON 容错。"""

import asyncio
import json
import shutil
import tempfile
from types import SimpleNamespace

import pytest

from app.config import ModelGatewayConfig, ProviderConfig
from app.llm.llm_client import LLMClient, LLMCallConfig, LLMCallResult


def _make_client(monkeypatch, create_fn):
    cfg = ModelGatewayConfig(
        default_model="fake-model",
        default_max_tokens=512,
        default_temperature=0.0,
        max_retries=2,
        request_timeout=5,
        providers=[
            ProviderConfig(name="fake", base_url="http://fake.local/v1",
                           api_key="k", models=["fake-model"])
        ],
    )
    client = LLMClient(cfg)
    monkeypatch.setattr(
        client._clients["fake"], "chat",
        SimpleNamespace(completions=SimpleNamespace(create=create_fn)),
    )
    return client


def _resp(content, prompt_tokens=5, completion_tokens=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens,
                              completion_tokens=completion_tokens),
    )


# ── schema 回显检测（skill 记录的真实事故）────────────────

async def test_schema_echo_detected(monkeypatch):
    """LLM 返回 schema 定义原文 → structured_output=None（降级 direct）。"""
    schema_text = json.dumps({
        "type": "object",
        "properties": {"intent": {"type": "string"}, "tool_selections": {"type": "array"}},
    })
    calls = {"n": 0}

    async def create_fn(**kwargs):
        calls["n"] += 1
        return _resp(schema_text)

    client = _make_client(monkeypatch, create_fn)
    result = await client.call(LLMCallConfig(
        system_prompt="你是 Mysu 的意图路由器…",
        user_prompt="用户消息",
        response_format={"type": "object", "properties": {
            "intent": {"type": "string"}, "tool_selections": {"type": "array"}}},
    ))
    assert result.structured_output is None  # 回显被识别为解析失败
    assert result.content == schema_text


# ── 重试 ────────────────────────────────────────────────────

async def test_retry_then_success(monkeypatch):
    """第一次失败 → 退避重试 → 第二次成功。"""
    calls = {"n": 0}

    async def create_fn(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset")
        return _resp('{"intent": "direct"}')

    async def _noop_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)  # 加速退避
    client = _make_client(monkeypatch, create_fn)
    result = await client.call(LLMCallConfig(
        system_prompt="s", user_prompt="u",
        response_format={"type": "object", "properties": {"intent": {"type": "string"}}},
    ))
    assert calls["n"] == 2
    assert result.structured_output == {"intent": "direct"}


async def test_all_retries_fail_raises(monkeypatch):
    async def create_fn(**kwargs):
        raise RuntimeError("always down")

    async def _noop_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    client = _make_client(monkeypatch, create_fn)
    with pytest.raises(RuntimeError, match="重试"):
        await client.call(LLMCallConfig(system_prompt="s", user_prompt="u"))


# ── JSON 容错 ───────────────────────────────────────────────

async def test_invalid_json_treated_as_text(monkeypatch):
    async def create_fn(**kwargs):
        return _resp("这不是 JSON")

    client = _make_client(monkeypatch, create_fn)
    result = await client.call(LLMCallConfig(system_prompt="s", user_prompt="u"))
    assert result.structured_output is None
    assert result.content == "这不是 JSON"


async def test_plain_string_parsed_is_not_dict(monkeypatch):
    """裸字符串（如 "direct"）不能当 dict 传给下游。"""
    async def create_fn(**kwargs):
        return _resp('"direct"')

    client = _make_client(monkeypatch, create_fn)
    result = await client.call(LLMCallConfig(
        system_prompt="s", user_prompt="u",
        response_format={"type": "object", "properties": {"intent": {"type": "string"}}},
    ))
    assert result.structured_output == "direct"  # 解析为字符串
    # Router 端对非 dict 有防御（_parse_decision 返回 direct）


# ── 全文落表（本次改造：不再 500 截断）────────────────────

async def test_log_call_to_db_full_content(monkeypatch, tmp_path):
    from app.storage.database import init_db, db_fetch_one
    init_db(str(tmp_path / "log.db"))

    client = _make_client(monkeypatch, lambda **kw: _resp("x"))
    result = LLMCallResult(
        content="R" * 600, structured_output={"abandon_clarify": True},
        tokens_in=1, tokens_out=2, model="m", latency_ms=1.0,
    )
    await client._log_call_to_db(
        LLMCallConfig(
            system_prompt="S" * 600, user_prompt="U" * 600,
            call_type="router", request_id="r1", session_id="s1",
        ),
        "m", "p", result, {"abandon_clarify": True},
    )
    row = await db_fetch_one(
        "SELECT system_prompt_snippet, user_prompt_snippet, response_snippet, "
        "structured_output_json FROM llm_call_logs WHERE request_id='r1'",
        _log=False,
    )
    assert len(row["system_prompt_snippet"]) == 600
    assert len(row["user_prompt_snippet"]) == 600
    assert len(row["response_snippet"]) == 600
    assert row["structured_output_json"] == '{"abandon_clarify": true}'


async def test_log_failure_to_db(monkeypatch, tmp_path):
    from app.storage.database import init_db, db_fetch_one
    init_db(str(tmp_path / "log2.db"))

    client = _make_client(monkeypatch, lambda **kw: _resp("x"))
    await client._log_failure_to_db(
        LLMCallConfig(system_prompt="S" * 600, user_prompt="U" * 600,
                      call_type="router", request_id="r2", session_id="s1"),
        "m", "p", "E" * 600,
    )
    row = await db_fetch_one(
        "SELECT success, length(error_message) as elen FROM llm_call_logs WHERE request_id='r2'",
        _log=False,
    )
    assert row["success"] == 0
    assert row["elen"] == 600
