"""确定性时间解析器单测——相对时间表达 → 具体日期。"""

from datetime import date

import pytest

from app.domain_packs.metacare._time_parser import parse_query_date

TODAY = date(2026, 8, 5)  # 周三


@pytest.mark.parametrize("text,expected", [
    ("今天", date(2026, 8, 5)),
    ("今日", date(2026, 8, 5)),
    ("明天", date(2026, 8, 6)),
    ("明日", date(2026, 8, 6)),
    ("后天", date(2026, 8, 7)),
    ("大后天", date(2026, 8, 8)),
    ("3天后", date(2026, 8, 8)),
    ("下周", date(2026, 8, 10)),          # 下周一
    ("下周运势", date(2026, 8, 10)),
    ("下周一", date(2026, 8, 10)),
    ("下周三", date(2026, 8, 12)),
    ("下周日", date(2026, 8, 16)),
    ("这周", date(2026, 8, 3)),           # 本周一
    ("本周", date(2026, 8, 3)),
    ("周一下周", date(2026, 8, 10)),       # 具体优先
    ("周三", date(2026, 8, 5)),           # 本周周三
    ("星期五", date(2026, 8, 7)),
    ("周日", date(2026, 8, 9)),
    ("上周一", date(2026, 7, 27)),
    ("2026-08-12", date(2026, 8, 12)),
    ("2026/08/12", date(2026, 8, 12)),
    ("2026年8月12日", date(2026, 8, 12)),
    ("8月12日", date(2026, 8, 12)),
])
def test_parse_query_date(text, expected):
    assert parse_query_date(text, TODAY) == expected


@pytest.mark.parametrize("text", [
    "", "  ", "随便聊聊", "帮我算塔罗", "不知道", "下个月",
])
def test_parse_query_date_unparseable(text):
    assert parse_query_date(text, TODAY) is None
