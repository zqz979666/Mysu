"""占星引擎纯函数测试（零 LLM，确定性计算）。"""

from datetime import date

from app.domain_packs.metacare._astrology_engine import (
    compute_planet_longitude,
    compute_natal_chart,
    compute_aspects,
    compute_transits,
    interpret_transits_for_horoscope,
    longitude_to_sign,
    longitude_to_sign_degree,
    compute_ascendant,
    get_planet_house,
)


# ── 星座映射 ─────────────────────────────────────────────────

def test_longitude_to_sign_boundaries():
    assert longitude_to_sign(0) == "aries"
    assert longitude_to_sign(29.9) == "aries"
    assert longitude_to_sign(30) == "taurus"
    assert longitude_to_sign(359) == "pisces"


def test_longitude_to_sign_degree():
    sign, deg = longitude_to_sign_degree(45)
    assert sign == "taurus"
    assert 15 <= deg < 16  # 45 - 30 = 15 度


# ── 行星位置 ─────────────────────────────────────────────────

def test_planet_longitude_range():
    for pid in ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]:
        lon = compute_planet_longitude(pid, date(1990, 6, 15))
        assert 0 <= lon < 360, f"{pid} 经度越界: {lon}"


# ── 本命星盘 ─────────────────────────────────────────────────

def test_natal_chart_sun_sign_june15():
    """1990-06-15 太阳应在双子座（5/21~6/21）。"""
    chart = compute_natal_chart(date(1990, 6, 15), "12:00")
    assert chart.sun_sign == "gemini"


def test_natal_chart_sun_sign_january():
    chart = compute_natal_chart(date(1990, 1, 15), "12:00")
    assert chart.sun_sign == "capricorn"


def test_natal_chart_structure():
    chart = compute_natal_chart(date(1990, 6, 15), "14:30")
    assert chart.birth_date == date(1990, 6, 15)
    assert chart.birth_time == "14:30"
    assert chart.moon_sign  # 有月亮星座
    assert chart.ascendant_sign  # 有上升星座
    assert len(chart.planet_positions) >= 10  # 十大行星
    assert len(chart.houses) == 12  # 12 宫
    assert len(chart.planet_houses) >= 10
    assert isinstance(chart.aspects, list)


def test_natal_chart_deterministic():
    """同一输入两次计算必须完全一致（纯函数）。"""
    c1 = compute_natal_chart(date(1990, 6, 15), "12:00")
    c2 = compute_natal_chart(date(1990, 6, 15), "12:00")
    assert c1.planet_positions == c2.planet_positions
    assert c1.ascendant_sign == c2.ascendant_sign
    assert [(a.planet1, a.planet2, a.aspect_type) for a in c1.aspects] == \
           [(a.planet1, a.planet2, a.aspect_type) for a in c2.aspects]


def test_birth_time_affects_ascendant():
    """出生时间影响上升星座（正午 vs 凌晨通常不同）。"""
    c_noon = compute_natal_chart(date(1990, 6, 15), "12:00")
    c_midnight = compute_natal_chart(date(1990, 6, 15), "00:00")
    assert c_noon.ascendant_sign != c_midnight.ascendant_sign


# ── 相位 ─────────────────────────────────────────────────────

def test_aspects_opposition():
    aspects = compute_aspects({"sun": 0.0, "moon": 180.0})
    assert any(a.aspect_type == "opposition" for a in aspects)


def test_aspects_square():
    aspects = compute_aspects({"sun": 0.0, "moon": 90.0})
    assert any(a.aspect_type == "square" for a in aspects)


def test_aspects_conjunction():
    aspects = compute_aspects({"sun": 0.0, "moon": 2.0})
    assert any(a.aspect_type == "conjunction" for a in aspects)


# ── 上升 / 宫位 ──────────────────────────────────────────────

def test_ascendant_in_range():
    sign, lon = compute_ascendant(date(1990, 6, 15), "12:00")
    assert sign in {s for s in ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
                                "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]}
    assert 0 <= lon < 360


def test_planet_house():
    assert 1 <= get_planet_house(0.0, 0.0) <= 12


# ── 流年 ─────────────────────────────────────────────────────

def test_transits_structure():
    chart = compute_natal_chart(date(1990, 6, 15), "12:00")
    natal = {pid: compute_planet_longitude(pid, date(1990, 6, 15)) for pid in
             ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]}
    transits = compute_transits(natal, date(2026, 8, 5))
    assert isinstance(transits, list)
    if transits:
        t = transits[0]
        assert t.transit_planet and t.natal_planet
        assert t.aspect_type in {"conjunction", "sextile", "square", "trine", "opposition"}
        assert t.impact_level in {"强", "中", "弱"}


def test_horoscope_interpretation_structure():
    chart = compute_natal_chart(date(1990, 6, 15), "12:00")
    natal = {pid: compute_planet_longitude(pid, date(1990, 6, 15)) for pid in
             ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]}
    transits = compute_transits(natal, date(2026, 8, 5))
    h = interpret_transits_for_horoscope(transits, chart)
    for domain in ["overall", "love", "work", "health"]:
        assert "level" in h[domain] and "text" in h[domain]
    assert "harmony_count" in h and "challenge_count" in h
    assert isinstance(h["key_transits"], list)
