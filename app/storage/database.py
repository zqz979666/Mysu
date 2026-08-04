"""
SQLite 数据库层——连接管理 + 建表。

所有持久化数据统一走此模块：
- 记忆系统：user_profiles / long_term_facts / readings / session_state
- LLM 调用记录：llm_call_logs
- 后续：session 归档、事件队列等

设计：单文件 SQLite + WAL 模式 + aiosqlite 异步访问
"""

import sqlite3
from pathlib import Path
from typing import Optional

# 轻量级：直接用标准库 sqlite3（线程安全），不用 aiosqlite 以减少依赖
# 所有数据库操作在专用线程中执行（通过 asyncio.to_thread）

_DB_PATH: Optional[str] = None


def init_db(db_path: str = "data/mysu.db") -> str:
    """初始化数据库：创建目录、连接、建表。

    Returns:
        数据库文件的绝对路径
    """
    global _DB_PATH
    path = Path(db_path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = str(path)

    conn = _get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    conn.close()

    return _DB_PATH


def get_db_path() -> str:
    """获取当前数据库路径"""
    if _DB_PATH is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（线程安全，每次调用创建新连接）"""
    if _DB_PATH is None:
        raise RuntimeError("数据库未初始化")
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # 每个连接都必须开启外键约束（sqlite 默认关闭）
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── 建表 ────────────────────────────────────────────────────

def _create_tables(conn: sqlite3.Connection) -> None:
    """创建所有表（IF NOT EXISTS 幂等）"""

    conn.executescript("""
        -- L0: 用户画像（长期不变的基本信息）
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            birth_date TEXT,         -- 出生日期 YYYY-MM-DD
            birth_time TEXT,         -- 出生时间 HH:MM
            birth_place TEXT,        -- 出生地点
            zodiac_sign TEXT,        -- 太阳星座
            moon_sign TEXT,          -- 月亮星座
            ascendant_sign TEXT,     -- 上升星座
            gender TEXT,             -- 性别
            name TEXT,               -- 昵称/称呼
            preferences TEXT,        -- JSON: {"theme":"dark","language":"zh"}
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- L1: 长期事实（"用户最近在找工作"、"喜欢猫"）
        CREATE TABLE IF NOT EXISTS long_term_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            fact_type TEXT NOT NULL,  -- "life_event" | "preference" | "relationship" | ...
            content TEXT NOT NULL,    -- 事实内容
            source_session_id TEXT,   -- 来源会话
            confidence REAL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_user ON long_term_facts(user_id);

        -- L2: 玄学记录（历史 readings：塔罗结果、星盘等）
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            tool_id TEXT NOT NULL,     -- "tarot_draw" | "birth_chart" | ...
            query TEXT,                -- 用户当时的提问
            result_json TEXT,          -- JSON 格式的工具输出
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_readings_user ON readings(user_id);
        CREATE INDEX IF NOT EXISTS idx_readings_session ON readings(session_id);

        -- L3: 短期状态（当前对话窗口，归档后可清理）
        CREATE TABLE IF NOT EXISTS session_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,   -- 对话轮次
            role TEXT NOT NULL,             -- "user" | "assistant" | "tool"
            content TEXT NOT NULL,
            metadata_json TEXT,             -- JSON: {"intent":"execute","tool_id":"tarot_draw"}
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_state_session ON session_state(session_id);

        -- LLM 调用记录
        CREATE TABLE IF NOT EXISTS llm_call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            call_type TEXT NOT NULL,      -- "router" | "generator" | "ingest"
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            tokens_in INTEGER NOT NULL DEFAULT 0,
            tokens_out INTEGER NOT NULL DEFAULT 0,
            latency_ms REAL NOT NULL DEFAULT 0.0,
            system_prompt_snippet TEXT,    -- 前 500 字符
            user_prompt_snippet TEXT,      -- 前 500 字符
            response_snippet TEXT,         -- 前 500 字符
            structured_output_json TEXT,   -- Router 的结构化输出
            success INTEGER NOT NULL DEFAULT 1,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_llm_logs_request ON llm_call_logs(request_id);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_session ON llm_call_logs(session_id);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_type ON llm_call_logs(call_type);

        -- 数据库操作日志（调试用）
        CREATE TABLE IF NOT EXISTS db_operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,      -- "execute" | "fetch_all" | "fetch_one"
            table_name TEXT NOT NULL,
            sql_snippet TEXT,
            params_json TEXT,
            row_count INTEGER NOT NULL DEFAULT 0,
            latency_ms REAL NOT NULL DEFAULT 0.0,
            success INTEGER NOT NULL DEFAULT 1,
            error_message TEXT,
            context TEXT,                 -- 调用来源（如 "memory_service"）
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_db_logs_table ON db_operation_logs(table_name);
        CREATE INDEX IF NOT EXISTS idx_db_logs_time ON db_operation_logs(created_at);

        -- 待澄清状态（用户缺信息时挂起，回答后恢复）
        CREATE TABLE IF NOT EXISTS pending_clarifications (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tool_id TEXT NOT NULL,        -- 等待哪个工具的参数
            missing_params TEXT NOT NULL, -- JSON 数组，如 ["birth_date"]
            ask_message TEXT NOT NULL,    -- 当时问用户的问题
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
        );
    """)


# ── 查询辅助 ────────────────────────────────────────────────

import asyncio
import time


async def db_execute(
    sql: str, params: tuple = (), *, _log: bool = True, context: str = ""
) -> int | None:
    """在后台线程执行单条 SQL（INSERT/UPDATE/DELETE），返回 lastrowid。"""
    t0 = time.monotonic()
    error: str | None = None

    def _run():
        conn = _get_conn()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid, cur.rowcount, None
        except Exception as e:
            return None, 0, e
        finally:
            conn.close()

    lastrowid, rowcount, err = await asyncio.to_thread(_run)

    if err is not None:
        error = str(err)

    if _log:
        from app.observability.db_logger import log_db_operation
        await log_db_operation(
            "execute", sql, params, row_count=rowcount,
            latency_ms=(time.monotonic() - t0) * 1000,
            success=err is None, error_message=error or "",
            context=context,
        )

    if err is not None:
        raise err

    return lastrowid


async def db_fetch_all(
    sql: str, params: tuple = (), *, _log: bool = True, context: str = ""
) -> list[sqlite3.Row]:
    """在后台线程查询多条记录。"""
    t0 = time.monotonic()
    error: str | None = None

    def _run():
        conn = _get_conn()
        try:
            cur = conn.execute(sql, params)
            return cur.fetchall()
        except Exception as e:
            return e
        finally:
            conn.close()

    result = await asyncio.to_thread(_run)

    if isinstance(result, BaseException):
        error = str(result)
        rows: list = []
        success = False
    else:
        rows = result
        success = True

    if _log:
        from app.observability.db_logger import log_db_operation
        await log_db_operation(
            "fetch_all", sql, params, row_count=len(rows),
            latency_ms=(time.monotonic() - t0) * 1000,
            success=success, error_message=error or "",
            context=context,
        )

    if not success:
        raise result  # type: ignore[misc]

    return rows


async def db_fetch_one(
    sql: str, params: tuple = (), *, _log: bool = True, context: str = ""
) -> sqlite3.Row | None:
    """在后台线程查询单条记录。"""
    t0 = time.monotonic()
    error: str | None = None

    def _run():
        conn = _get_conn()
        try:
            cur = conn.execute(sql, params)
            return cur.fetchone()
        except Exception as e:
            return e
        finally:
            conn.close()

    result = await asyncio.to_thread(_run)

    if isinstance(result, BaseException):
        error = str(result)
        row = None
        success = False
    else:
        row = result
        success = True

    if _log:
        from app.observability.db_logger import log_db_operation
        await log_db_operation(
            "fetch_one", sql, params, row_count=1 if row else 0,
            latency_ms=(time.monotonic() - t0) * 1000,
            success=success, error_message=error or "",
            context=context,
        )

    if not success:
        raise result  # type: ignore[misc]

    return row
