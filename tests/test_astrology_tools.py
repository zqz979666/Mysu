"""占星工具测试：validate_params（澄清闸门依据）+ execute 输出结构。"""

from datetime import date

import pytest

from app.domain_packs.metacare.astrology import (
    BirthChartTool,
    DailyTransitTool,
    HoroscopeDailyTool,
)
from app.models.domain import ExecutionContext


@pytest.fixture
def ctx():
    return ExecutionContext(session_id="s1", user_id="u1", request_id="r1")


# ── validate_params（澄清闸门核心）──────────────────────────

def test_birth_chart_requires_birth_date():
    t = BirthChartTool()
    assert t.validate_params({}) == ["birth_date"]
    assert t.validate_params({"sign": "aries"}) == ["birth_date"]  # 星座不能代替生日
    assert t.validate_params({"birth_date": "1995-06-15"}) == []


def test_daily_transit_requires_birth_date():
    t = DailyTransitTool()
    assert t.validate_params({}) == ["birth_date"]
    assert t.validate_params({"birth_date": "1995-06-15"}) == []


def test_horoscope_daily_or_constraint():
    """sign 或 birth_date 至少一个（OR 约束）。"""
    t = HoroscopeDailyTool()
    assert t.validate_params({}) == ["sign 或 birth_date"]
    assert t.validate_params({"sign": "白羊座"}) == []
    assert t.validate_params({"birth_date": "1995-06-15"}) == []
    assert t.validate_params({"sign": "白羊座", "birth_date": "1995-06-15"}) == []


# ── birth_chart 执行 ─────────────────────────────────────────

async def test_birth_chart_execute(ctx):
    result = await BirthChartTool().execute({"birth_date": "1995-06-15", "birth_time": "14:30"}, ctx)
    assert result.success
    out = result.output
    assert out["birth_date"] == "1995-06-15"
    assert out["birth_time"] == "14:30"
    assert "太阳" in out["sun_sign"] or "双子" in out["sun_sign"]
    assert len(out["planets"]) == 10
    assert len(out["houses"]) == 12
    assert len(out["aspects"]) > 0
    assert "执行: birth_chart" in result.trace


async def test_birth_chart_default_time(ctx):
    result = await BirthChartTool().execute({"birth_date": "1995-06-15"}, ctx)
    assert result.success
    assert result.output["birth_time"] == "12:00"


# ── daily_transit 执行 ───────────────────────────────────────

async def test_daily_transit_execute(ctx):
    result = await DailyTransitTool().execute(
        {"birth_date": "1995-06-15", "date": "2026-08-05"}, ctx
    )
    assert result.success
    out = result.output
    assert out["query_date"] == "2026-08-05"
    assert isinstance(out["transit_aspects"], list)
    assert "horoscope" in out
    assert "执行: daily_transit" in result.trace


# ── horoscope_daily 执行 ─────────────────────────────────────

async def test_horoscope_general_mode(ctx):
    result = await HoroscopeDailyTool().execute({"sign": "白羊座"}, ctx)
    assert result.success
    out = result.output
    assert out["mode"] == "general"
    assert out["sign"] == "白羊座"
    for k in ["overall", "love", "work", "health"]:
        assert "level" in out[k] and "text" in out[k]


async def test_horoscope_personalized_mode(ctx):
    result = await HoroscopeDailyTool().execute(
        {"birth_date": "1995-06-15", "birth_time": "14:30"}, ctx
    )
    assert result.success
    out = result.output
    assert out["mode"] == "personalized_transit"
    assert out["date"]
    assert out["harmony_count"] >= 0
    assert "执行: horoscope_daily" in result.trace


async def test_horoscope_invalid_sign(ctx):
    result = await HoroscopeDailyTool().execute({"sign": "火星人"}, ctx)
    assert not result.success
    assert "无法识别星座" in (result.error or "")


# ── horoscope_daily 的 date 参数（下周/明天等）────────────────

async def test_horoscope_general_with_absolute_date(ctx):
    """指定绝对日期 → 按该日期计算并回显。"""
    result = await HoroscopeDailyTool().execute(
        {"sign": "白羊座", "date": "2026-08-12"}, ctx
    )
    assert result.success
    out = result.output
    assert out is not None
    assert out["mode"] == "general"
    assert out["date"] == "2026-08-12"


async def test_horoscope_general_with_relative_date(ctx):
    """相对时间（明天）→ 解析为具体日期，不能是今天。"""
    from datetime import timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    result = await HoroscopeDailyTool().execute(
        {"sign": "白羊座", "date": "明天"}, ctx
    )
    assert result.success
    out = result.output
    assert out is not None
    assert out["mode"] == "general"
    assert out["date"] == tomorrow


async def test_horoscope_personalized_with_date(ctx):
    """个性化模式：date 生效，流年按查询日计算。"""
    result = await HoroscopeDailyTool().execute(
        {"birth_date": "1995-06-15", "date": "下周"}, ctx
    )
    assert result.success
    out = result.output
    assert out is not None
    assert out["mode"] == "personalized_transit"
    assert out["date"] != date.today().isoformat()
    assert result.trace is not None
    assert "query_date" in result.trace


async def test_horoscope_default_date_is_today(ctx):
    """不传 date → 默认今天。"""
    result = await HoroscopeDailyTool().execute({"sign": "白羊座"}, ctx)
    assert result.success
    out = result.output
    assert out is not None
    assert out["date"] == date.today().isoformat()
