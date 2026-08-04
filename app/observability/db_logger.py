"""
数据库操作日志——记录每次 DB 读写的完整信息。

双通道：
1. 结构化日志（stdout，实时）
2. db_operation_logs 表（持久化，可 debug 查询）

关键设计：
- 记录操作类型、涉及表、SQL 摘要、参数、影响行数、耗时、错误
- 对 db_operation_logs 自身的写入不递归记录（防循环）
- 所有 DB 日志函数都是异步的，不阻塞业务路径
"""

import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger("mysu.db")


# ── 工具函数 ────────────────────────────────────────────────

_TABLE_PATTERN = re.compile(
    r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|INTO)\s+([\w_]+)",
    re.IGNORECASE,
)


def extract_table_name(sql: str) -> str:
    """从 SQL 中提取主要操作的表名"""
    m = _TABLE_PATTERN.search(sql)
    if m:
        table = m.group(1)
        # 排除子查询引入的干扰表
        if table in ("sqlite_master",):
            return "meta"
        return table
    return "unknown"


def _summarize_params(params: tuple) -> str:
    """参数摘要（截断长值，防止日志膨胀）"""
    if not params:
        return "[]"
    items = []
    for p in params:
        s = str(p)
        items.append(s[:80] + "..." if len(s) > 80 else s)
    return json.dumps(items, ensure_ascii=False)


# ── 落表 ────────────────────────────────────────────────────

async def log_db_operation(
    operation: str,          # "execute" | "fetch_all" | "fetch_one"
    sql: str,
    params: tuple = (),
    row_count: int = 0,
    latency_ms: float = 0.0,
    success: bool = True,
    error_message: str = "",
    context: str = "",       # 可选：调用来源说明（如 "profile_extractor"）
) -> None:
    """记录一次数据库操作。对 db_operation_logs 自身不记录。"""
    table = extract_table_name(sql)
    if table == "db_operation_logs":
        return

    # ── stdout 结构化日志 ─────────────────────────
    status = "OK" if success else "ERR"
    extra = f"table={table} rows={row_count} latency={latency_ms:.1f}ms"
    if context:
        extra += f" ctx={context}"
    if error_message:
        extra += f" error={error_message[:150]}"
    logger.info(f"DB {operation} [{status}] {extra} | sql={sql[:120]}")

    # ── 落表 ──────────────────────────────────────
    try:
        from app.storage.database import db_execute as _exec
        await _exec(
            """INSERT INTO db_operation_logs (
                operation, table_name, sql_snippet, params_json,
                row_count, latency_ms, success, error_message, context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                operation,
                table,
                sql[:200],
                _summarize_params(params),
                row_count,
                latency_ms,
                1 if success else 0,
                error_message[:500],
                context,
            ),
        )
    except Exception as e:
        logger.error(f"DB 操作日志落表失败: {e}")
