"""SQLite 数据层测试：commit 语义、FK 约束、操作日志。"""

import sqlite3

import pytest

from app.storage import database
from app.storage.database import (
    init_db, get_db_path, db_execute, db_fetch_one, db_fetch_all,
)


async def test_init_db_idempotent(tmp_path):
    path = str(tmp_path / "a.db")
    init_db(path)
    init_db(path)  # 重复初始化不炸（IF NOT EXISTS）
    assert get_db_path() == str(tmp_path / "a.db")


async def test_write_immediately_visible(tmp_db_path):
    """db_execute 自带 commit——写入后立即可查（历史事故：漏 commit 静默回滚）。"""
    await db_execute(
        "INSERT INTO user_profiles (user_id, name) VALUES (?, ?)",
        ("u1", "小明"),
    )
    row = await db_fetch_one(
        "SELECT name FROM user_profiles WHERE user_id=?", ("u1",)
    )
    assert row["name"] == "小明"


async def test_fk_constraint_enforced(tmp_db_path):
    """FK 必须生效（每连接 PRAGMA foreign_keys=ON）。"""
    with pytest.raises(sqlite3.IntegrityError):
        await db_execute(
            "INSERT INTO pending_clarifications (session_id, user_id, tool_id, missing_params, ask_message) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s1", "ghost_user", "tarot_draw", "[]", "q"),
        )


async def test_db_operation_logging(tmp_db_path):
    await db_execute("INSERT INTO user_profiles (user_id) VALUES (?)", ("u1",))
    rows = await db_fetch_all(
        "SELECT operation, table_name FROM db_operation_logs ORDER BY id DESC LIMIT 3",
        _log=False,
    )
    ops = [r["table_name"] for r in rows]
    assert "user_profiles" in ops


async def test_db_log_self_recursion_guard(tmp_db_path):
    """查询 db_operation_logs 本身不产生新的日志（防自递归）。"""
    await db_execute("INSERT INTO user_profiles (user_id) VALUES (?)", ("u1",))
    await db_fetch_all(
        "SELECT * FROM db_operation_logs LIMIT 1", _log=False,
    )
    count = await db_fetch_one(
        "SELECT COUNT(*) as c FROM db_operation_logs", _log=False,
    )
    # 只有前面 INSERT 产生的 1 条（没有因查询本身再插入）
    assert count["c"] == 1


async def test_reset_order_children_first(tmp_db_path):
    """重置顺序：先删子表再删父表（FK 约束）。"""
    await db_execute("INSERT INTO user_profiles (user_id) VALUES (?)", ("u1",))
    await db_execute("INSERT INTO readings (session_id, user_id, tool_id) VALUES (?, ?, ?)", ("s1", "u1", "tarot_draw"))
    # 子表删除成功
    await db_execute("DELETE FROM readings WHERE user_id=?", ("u1",))
    await db_execute("DELETE FROM user_profiles WHERE user_id=?", ("u1",))
    row = await db_fetch_one("SELECT * FROM user_profiles WHERE user_id=?", ("u1",))
    assert row is None


async def test_delete_profile_blocked_by_pending_fk(tmp_db_path):
    """pending_clarifications 引用画像时直接删 user_profiles 会 FK 失败（reset 历史事故）。"""
    await db_execute("INSERT INTO user_profiles (user_id) VALUES (?)", ("u1",))
    await db_execute(
        "INSERT INTO pending_clarifications (session_id, user_id, tool_id, missing_params, ask_message) "
        "VALUES (?, ?, ?, ?, ?)",
        ("s1", "u1", "horoscope_daily", '["sign 或 birth_date"]', "q"),
    )
    # 必须先删 pending 再删画像
    with pytest.raises(sqlite3.IntegrityError):
        await db_execute("DELETE FROM user_profiles WHERE user_id=?", ("u1",))
    await db_execute("DELETE FROM pending_clarifications WHERE user_id=?", ("u1",))
    await db_execute("DELETE FROM user_profiles WHERE user_id=?", ("u1",))
    row = await db_fetch_one("SELECT * FROM user_profiles WHERE user_id=?", ("u1",))
    assert row is None


async def test_tables_created(tmp_db_path):
    rows = await db_fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'", _log=False,
    )
    names = {r["name"] for r in rows}
    expected = {
        "user_profiles", "long_term_facts", "readings", "session_state",
        "llm_call_logs", "db_operation_logs", "pending_clarifications",
        "memory_extractions",
    }
    assert expected <= names
