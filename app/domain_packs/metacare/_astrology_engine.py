"""
占星计算引擎——纯函数、确定性、零 LLM。

核心能力：
1. 行星黄道经度计算（简化轨道模型）
2. 星座/宫位映射
3. 相位计算（合/六合/刑/三合/冲）
4. 流年星象 Transits
5. 本命盘（Natal Chart）生成

设计原则：
- 所有计算是确定性的：同一个日期/时间 → 同一个结果
- 全流程日志覆盖：每个计算步骤都有结构化日志
- 零 LLM 调用：纯数学 + 数据查找，LLM 只在表达层做解读
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from app.domain_packs.metacare._astrology_data import (
    ZODIAC_SIGNS, ZodiacSign,
    PLANETS, Planet,
    HOUSES, House,
    ASPECT_TYPES, AspectType,
    PLANET_RULERSHIP, PLANET_EXALTATION,
    get_planet_dignity,
    resolve_sign,
)

logger = logging.getLogger("mysu.astrology_engine")


# ── J2000 纪元 ─────────────────────────────────────────────

_J2000 = datetime(2000, 1, 1, 12, 0, 0)  # January 1, 2000, 12:00 TT


def _days_since_j2000(d: date) -> float:
    """计算给定日期距离 J2000 的天数"""
    dt = datetime(d.year, d.month, d.day, 12, 0, 0)
    return (dt - _J2000).total_seconds() / 86400.0


# ── 行星经度基准值 (J2000 时刻的近似位置 + 轨道参数) ──────

# 每颗行星在 J2000 时刻的黄道经度（度）和日均角速度（度/天）
_PLANET_ORBITAL_PARAMS: dict[str, tuple[float, float]] = {
    # planet_id: (J2000_longitude_deg, mean_daily_motion_deg)
    "sun":     (280.46, 0.9856474),
    "moon":    (218.32, 13.176396),
    "mercury": (252.25, 4.092317),
    "venus":   (181.98, 1.602130),
    "mars":    (355.43, 0.524021),
    "jupiter": (34.35,  0.083085),
    "saturn":  (50.08,  0.033444),
    "uranus":  (314.06, 0.011728),
    "neptune": (304.22, 0.005981),
    "pluto":   (249.05, 0.003964),
}


def compute_planet_longitude(planet_id: str, d: date) -> float:
    """计算行星在指定日期的黄道经度（0-360 度）。

    Args:
        planet_id: 行星 ID
        d: 日期

    Returns:
        黄道经度（度），0°=白羊座起点
    """
    if planet_id not in _PLANET_ORBITAL_PARAMS:
        raise ValueError(f"未知行星: {planet_id}")

    base_lon, daily_motion = _PLANET_ORBITAL_PARAMS[planet_id]
    days = _days_since_j2000(d)

    # 简化：均值运动
    longitude = (base_lon + daily_motion * days) % 360.0

    logger.debug(
        f"  行星位置: {planet_id} | J2000+{days:.0f}d "
        f"| 经度={longitude:.1f}°"
    )

    return longitude


def longitude_to_sign(longitude: float) -> str:
    """将黄道经度映射到星座 ID。

    白羊座 = 0°-30°, 金牛座 = 30°-60°, ...
    """
    sign_index = int(longitude / 30) % 12
    sign_ids = list(ZODIAC_SIGNS.keys())
    return sign_ids[sign_index]


def longitude_to_sign_degree(longitude: float) -> tuple[str, float]:
    """返回 (星座ID, 星座内度数)"""
    sign_id = longitude_to_sign(longitude)
    degree_in_sign = longitude % 30
    return sign_id, round(degree_in_sign, 2)


# ── 上升星座与宫位计算 ─────────────────────────────────────

def compute_ascendant(birth_date: date, birth_time: str = "12:00") -> tuple[str, float]:
    """计算上升星座（简化等宫位系统）。

    简化模型：基于日出时刻推算 ASC。
    实际 ASC = 出生时间相对于当地日出时间的偏移，每 2 小时移动一个星座。
    这里用正午12点为参考——凌晨0点出生 = ASC 比太阳靠前6个星座。

    Args:
        birth_date: 出生日期
        birth_time: 出生时间 "HH:MM"

    Returns:
        (ASC 星座 id, ASC 经度)
    """
    # 解析出生时间
    try:
        parts = birth_time.strip().split(":")
        hour = int(parts[0]) + int(parts[1]) / 60.0 if len(parts) > 1 else int(parts[0])
    except (ValueError, IndexError):
        hour = 12.0

    # 太阳位置
    sun_lon = compute_planet_longitude("sun", birth_date)

    # 简化：正午12点 ASC ≈ 太阳位置
    # 每偏离正午1小时，ASC 偏移约15°（一个星座约2小时）
    hour_offset = hour - 12.0
    asc_offset_deg = hour_offset * 15.0  # 每1小时 ≈ 15°

    asc_lon = (sun_lon + asc_offset_deg) % 360.0

    logger.debug(
        f"  上升计算: birth_time={birth_time} hour_offset={hour_offset:+.1f}h "
        f"| sun_lon={sun_lon:.1f}° asc_offset={asc_offset_deg:+.1f}° "
        f"| asc_lon={asc_lon:.1f}°"
    )

    sign_id = longitude_to_sign(asc_lon)
    return sign_id, asc_lon


def compute_houses(asc_longitude: float) -> dict[int, tuple[str, float, float]]:
    """等宫位系统：从 ASC 开始，每个宫位 30°。

    Returns:
        {house_number: (sign_id, house_start_lon, house_mid_lon)}
    """
    houses: dict[int, tuple[str, float, float]] = {}
    for h in range(1, 13):
        cusp_lon = (asc_longitude + (h - 1) * 30.0) % 360.0
        mid_lon = (cusp_lon + 15.0) % 360.0
        sign_id = longitude_to_sign(cusp_lon)
        houses[h] = (sign_id, cusp_lon, mid_lon)
    return houses


def get_planet_house(planet_longitude: float, asc_longitude: float) -> int:
    """计算行星落入的宫位"""
    relative_lon = (planet_longitude - asc_longitude) % 360.0
    house = int(relative_lon / 30.0) + 1
    return house


# ── 相位计算 ────────────────────────────────────────────────

@dataclass
class Aspect:
    """两个行星之间的相位"""
    planet1: str
    planet2: str
    aspect_type: str            # conjunction/sextile/square/trine/opposition
    angle_actual: float         # 实际夹角（度）
    angle_target: float         # 目标夹角（度）
    orb: float                  # 实际偏差（度）
    nature: str                 # "和谐" | "挑战" | "中性"


def _angular_distance(lon1: float, lon2: float) -> float:
    """两个经度之间的最短弧距（0-180°）"""
    diff = abs(lon1 - lon2) % 360.0
    return min(diff, 360.0 - diff)


def compute_aspects(positions: dict[str, float]) -> list[Aspect]:
    """计算所有行星两两之间的相位。

    Args:
        positions: {planet_id: longitude_deg}

    Returns:
        相位列表（按行星对排序）
    """
    aspects: list[Aspect] = []
    planet_ids = list(positions.keys())

    for i in range(len(planet_ids)):
        for j in range(i + 1, len(planet_ids)):
            p1, p2 = planet_ids[i], planet_ids[j]
            lon1, lon2 = positions[p1], positions[p2]
            dist = _angular_distance(lon1, lon2)

            for aspect_id, aspect_def in ASPECT_TYPES.items():
                diff = abs(dist - aspect_def.angle)
                # 处理合相的特殊情况（也检查 360°）
                if aspect_id == "conjunction":
                    diff = min(diff, abs(360.0 - dist - aspect_def.angle))

                if diff <= aspect_def.orb:
                    aspects.append(Aspect(
                        planet1=p1, planet2=p2,
                        aspect_type=aspect_id,
                        angle_actual=round(dist, 1),
                        angle_target=aspect_def.angle,
                        orb=round(diff, 1),
                        nature=aspect_def.nature,
                    ))
                    if len(aspects) > 0:
                        logger.debug(
                            f"  相位: {p1} △ {p2} → {aspect_def.name} "
                            f"(实际={dist:.1f}° 目标={aspect_def.angle}° orb={diff:.1f}°)"
                        )
                    break  # 取最接近的相位类型

    return aspects


# ── 流年星象 Transit 计算 ───────────────────────────────────

@dataclass
class TransitAspect:
    """一个流年相位：当前行星 vs 本命行星"""
    transit_planet: str
    natal_planet: str
    aspect_type: str
    angle_actual: float
    orb: float
    nature: str
    # 影响评估
    transit_sign: str = ""       # 流年行星所在星座
    natal_sign: str = ""         # 本命行星所在星座
    impact_level: str = ""       # "强" | "中" | "弱"


def compute_transits(
    natal_positions: dict[str, float],
    transit_date: date,
) -> list[TransitAspect]:
    """计算流年星象：当前行星位置 vs 本命盘行星位置。

    Args:
        natal_positions: 本命盘中各行星的 {planet_id: longitude}
        transit_date: 流年日期

    Returns:
        流年相位列表
    """
    logger.info(
        f"  流年计算开始: {transit_date.isoformat()} "
        f"| 本命行星: {list(natal_positions.keys())}"
    )

    # 计算当前行星位置
    transit_positions: dict[str, float] = {}
    for planet_id in PLANETS:
        transit_positions[planet_id] = compute_planet_longitude(planet_id, transit_date)

    transits: list[TransitAspect] = []

    # 只检查快速移动行星的流年 × 所有本命行星
    from app.domain_packs.metacare._astrology_data import FAST_PLANETS
    for t_planet in FAST_PLANETS:
        t_lon = transit_positions[t_planet]
        for n_planet, n_lon in natal_positions.items():
            dist = _angular_distance(t_lon, n_lon)
            for aspect_id, aspect_def in ASPECT_TYPES.items():
                diff = abs(dist - aspect_def.angle)
                if aspect_id == "conjunction":
                    diff = min(diff, abs(360.0 - dist - aspect_def.angle))
                if diff <= aspect_def.orb:
                    impact = "强" if diff <= aspect_def.orb * 0.3 else ("中" if diff <= aspect_def.orb * 0.6 else "弱")
                    transits.append(TransitAspect(
                        transit_planet=t_planet,
                        natal_planet=n_planet,
                        aspect_type=aspect_id,
                        angle_actual=round(dist, 1),
                        orb=round(diff, 1),
                        nature=aspect_def.nature,
                        transit_sign=longitude_to_sign(t_lon),
                        natal_sign=longitude_to_sign(n_lon),
                        impact_level=impact,
                    ))

    logger.info(
        f"  流年计算完成: {len(transits)} 个有效流年相位 "
        f"| 和谐={sum(1 for t in transits if t.nature=='和谐')} "
        f"挑战={sum(1 for t in transits if t.nature=='挑战')} "
        f"中性={sum(1 for t in transits if t.nature=='中性')}"
    )

    return transits


# ── 本命盘生成 ──────────────────────────────────────────────

@dataclass
class NatalChart:
    """一张完整的本命星盘"""
    birth_date: date
    birth_time: str  # "HH:MM"
    # 太阳/月亮/上升
    sun_sign: str = ""
    moon_sign: str = ""
    ascendant_sign: str = ""
    # 所有行星位置
    planet_positions: dict[str, tuple[str, float]] = field(default_factory=dict)
    # 宫位信息
    asc_longitude: float = 0.0
    houses: dict[int, tuple[str, float, float]] = field(default_factory=dict)
    planet_houses: dict[str, int] = field(default_factory=dict)
    # 相位
    aspects: list[Aspect] = field(default_factory=list)


def compute_natal_chart(birth_date: date, birth_time: str = "12:00") -> NatalChart:
    """生成本命星盘。

    Args:
        birth_date: 出生日期
        birth_time: 出生时间 "HH:MM"（默认正午）

    Returns:
        完整的 NatalChart
    """
    logger.info(
        f"══════ 本命盘计算开始 ══════\n"
        f"  出生日期: {birth_date.isoformat()} | 出生时间: {birth_time}"
    )

    chart = NatalChart(birth_date=birth_date, birth_time=birth_time)

    # ── 1. 计算所有行星位置 ──────────────────────
    logger.info("  [1/5] 计算行星黄道经度...")
    positions: dict[str, float] = {}
    for planet_id in PLANETS:
        lon = compute_planet_longitude(planet_id, birth_date)
        positions[planet_id] = lon
        sign_id, deg = longitude_to_sign_degree(lon)
        chart.planet_positions[planet_id] = (sign_id, deg)

    # 太阳/月亮星座
    chart.sun_sign = chart.planet_positions["sun"][0]
    chart.moon_sign = chart.planet_positions["moon"][0]

    sun_info = ZODIAC_SIGNS[chart.sun_sign]
    moon_info = ZODIAC_SIGNS[chart.moon_sign]
    logger.info(
        f"  太阳星座: {sun_info.symbol} {sun_info.name} | "
        f"月亮星座: {moon_info.symbol} {moon_info.name}"
    )

    # ── 2. 计算上升星座和宫位 ────────────────────
    logger.info("  [2/5] 计算上升星座和宫位...")
    asc_sign, asc_lon = compute_ascendant(birth_date, birth_time)
    chart.ascendant_sign = asc_sign
    chart.asc_longitude = asc_lon
    chart.houses = compute_houses(asc_lon)

    asc_info = ZODIAC_SIGNS[asc_sign]
    logger.info(f"  上升星座: {asc_info.symbol} {asc_info.name}")

    # ── 3. 计算每个行星落入的宫位 ─────────────────
    logger.info("  [3/5] 分配行星到宫位...")
    for planet_id, lon in positions.items():
        house_num = get_planet_house(lon, asc_lon)
        chart.planet_houses[planet_id] = house_num
        house_info = HOUSES[house_num]
        logger.debug(
            f"  {PLANETS[planet_id].symbol} {PLANETS[planet_id].name} "
            f"在 {chart.planet_positions[planet_id][0]} "
            f"→ 第{house_num}宫 ({house_info.name})"
        )

    # ── 4. 计算行星相位 ──────────────────────────
    logger.info("  [4/5] 计算行星相位...")
    chart.aspects = compute_aspects(positions)
    harmony = sum(1 for a in chart.aspects if a.nature == "和谐")
    challenge = sum(1 for a in chart.aspects if a.nature == "挑战")
    neutral = sum(1 for a in chart.aspects if a.nature == "中性")
    logger.info(f"  相位总计: {len(chart.aspects)} 个 | 和谐={harmony} 挑战={challenge} 中性={neutral}")

    # ── 5. 输出摘要 ──────────────────────────────
    logger.info(
        f"══════ 本命盘计算完成 ══════\n"
        f"  结果: {sun_info.symbol}☉{sun_info.name} "
        f"{moon_info.symbol}☽{moon_info.name} "
        f"{asc_info.symbol}↑{asc_info.name} "
        f"| 宫位={len(chart.houses)} 相位={len(chart.aspects)}"
    )

    return chart


# ── 运势生成辅助 ────────────────────────────────────────────

def interpret_transits_for_horoscope(
    transits: list[TransitAspect],
    natal_chart: NatalChart,
) -> dict:
    """基于流年相位生成结构化的运势解读数据。

    Returns:
        {
            "overall": {"level", "text"},
            "love": {"level", "text"},
            "work": {"level", "text"},
            "health": {"level", "text"},
            "key_transits": [...]  # 最重要的几个流年相位
        }
    """
    logger.info("  [运势解读] 基于流年相位生成运势...")

    # 分类：哪些流年影响哪些生活领域
    love_transits = []
    work_transits = []
    health_transits = []

    for t in transits:
        # 金星/月亮流年 → 爱情/情绪
        if t.transit_planet in ("venus", "moon") or t.natal_planet in ("venus", "moon"):
            love_transits.append(t)
        # 火星/土星/太阳流年 → 事业/行动
        if t.transit_planet in ("mars", "saturn", "sun", "jupiter") or t.natal_planet in ("mars", "saturn", "sun"):
            work_transits.append(t)
        # 火星/土星流年 → 健康/精力
        if t.transit_planet in ("mars", "saturn") or t.natal_planet in ("mars", "saturn"):
            health_transits.append(t)

    # 评估等级
    def _eval_level(transits_list: list[TransitAspect]) -> tuple[str, str]:
        if not transits_list:
            return ("⭐⭐ 平", "今日此领域无显著星象影响，按日常节奏推进即可。")
        harmony_count = sum(1 for t in transits_list if t.nature == "和谐")
        challenge_count = sum(1 for t in transits_list if t.nature == "挑战")
        strong_impacts = sum(1 for t in transits_list if t.impact_level == "强")

        if harmony_count >= 2 and challenge_count == 0:
            return ("⭐⭐⭐ 旺", "星象和谐有力，此领域今日运势走高，适合主动出击。")
        elif challenge_count >= 2 and harmony_count == 0:
            return ("⭐ 弱", "星象提示此领域需谨慎行事。挑战是成长的契机，稳扎稳打为上。")
        elif strong_impacts >= 1:
            return ("⭐⭐⭐ 旺" if harmony_count > challenge_count else "⭐ 弱",
                    "今日此领域星象活跃，影响力较强，请留意相关事件的发展。")
        else:
            return ("⭐⭐ 平", "星象力量温和，此领域按日常节奏推进即可。")

    love_level, love_text = _eval_level(love_transits)
    work_level, work_text = _eval_level(work_transits)
    health_level, health_text = _eval_level(health_transits)

    # 综合评级
    all_counts = {"和谐": 0, "挑战": 0}
    for t in transits:
        all_counts[t.nature] = all_counts.get(t.nature, 0) + 1

    if all_counts["和谐"] >= 3 and all_counts["挑战"] <= 1:
        overall_level = "⭐⭐⭐ 旺"
        overall_text = "今日星象总体和谐，多个流年相位为你带来顺遂的能量。把握时机主动出击，收获可期。"
    elif all_counts["挑战"] >= 3:
        overall_level = "⭐ 弱"
        overall_text = "今日星象充满张力，多个挑战相位提示你需要更多耐心和智慧。放慢脚步，稳中求进。"
    else:
        overall_level = "⭐⭐ 平"
        overall_text = "今日星象喜忧参半，生活按正常节奏推进。留意流年具体影响，做好当下事便是最好的应对。"

    # 提取前 3 个最重要的流年相位
    key_transits = sorted(transits, key=lambda t: (
        -1 if t.impact_level == "强" else (0 if t.impact_level == "中" else 1),
        t.orb
    ))[:3]

    key_transit_info = []
    for t in key_transits:
        aspect_def = ASPECT_TYPES[t.aspect_type]
        t_planet = PLANETS[t.transit_planet]
        n_planet = PLANETS[t.natal_planet]
        key_transit_info.append({
            "transit_planet": f"{t_planet.symbol}{t_planet.name}",
            "natal_planet": f"{n_planet.symbol}{n_planet.name}",
            "aspect": aspect_def.name,
            "nature": aspect_def.nature,
            "impact": t.impact_level,
            "interpretation": f"流年{t_planet.name}与你的本命{n_planet.name}形成{aspect_def.name}，"
                              f"偏差{t.orb}°。{aspect_def.interpretation}",
        })

    logger.info(
        f"  [运势解读] 综合={overall_level} 爱情={love_level} 事业={work_level} 健康={health_level} "
        f"| 关键相位={len(key_transit_info)}"
    )

    return {
        "overall": {"level": overall_level, "text": overall_text},
        "love": {"level": love_level, "text": love_text},
        "work": {"level": work_level, "text": work_text},
        "health": {"level": health_level, "text": health_text},
        "total_transits": len(transits),
        "harmony_count": all_counts.get("和谐", 0),
        "challenge_count": all_counts.get("挑战", 0),
        "key_transits": key_transit_info,
    }
