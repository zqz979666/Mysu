"""SessionManager 单元测试。"""

import pytest

from app.agent.session_manager import SessionManager


async def test_create_new_session():
    sm = SessionManager()
    s = await sm.get_or_create(None, "u1")
    assert s.session_id.startswith("sess_")
    assert s.user_id == "u1"
    assert s.status == "active"


async def test_reuse_existing_session():
    sm = SessionManager()
    s1 = await sm.get_or_create("sid-1", "u1")
    s2 = await sm.get_or_create("sid-1", "u1")
    assert s1 is s2  # 同一对象


async def test_explicit_session_id():
    sm = SessionManager()
    s = await sm.get_or_create("my-session", "u1")
    assert s.session_id == "my-session"


async def test_archive():
    sm = SessionManager()
    s = await sm.get_or_create("sid-1", "u1")
    await sm.archive("sid-1")
    assert s.status == "archived"


async def test_should_split_not_implemented():
    sm = SessionManager()
    assert await sm.should_split("sid-1", "direct") is False
