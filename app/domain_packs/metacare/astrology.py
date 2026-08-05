"""
星座 Skill — 基于真实星象计算的占星工具。

三个 ToolSpec：
- birth_chart:     生成本命星盘（行星位置 + 宫位 + 相位）
- daily_transit:    今日流年星象 vs 本命盘
- horoscope_daily:  每日星座运势（基于流年 Transit 计算，非随机）

所有工具零 LLM 调用——纯确定性计算。
日志覆盖全流程：每一步输入/输出/耗时都有结构化日志。
"""

import logging
from datetime import date, datetime

from app.models.domain import ToolSpec, ToolResult, ExecutionContext
from app.domain_packs.metacare._astrology_data import (
    ZODIAC_SIGNS,
    PLANETS,
    HOUSES,
    ASPECT_TYPES,
    resolve_sign,
    get_planet_dignity,
)
from app.domain_packs.metacare._astrology_engine import (
    compute_natal_chart,
    compute_transits,
    interpret_transits_for_horoscope,
)
from app.domain_packs.metacare._time_parser import parse_query_date

logger = logging.getLogger("mysu.astrology")


# ── 共享辅助 ────────────────────────────────────────────────

def _step_log(msg: str, **kwargs) -> None:
    """统一的步骤日志输出"""
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.info(f"  {msg}" + (f" | {extra}" if extra else ""))


def _parse_date(date_str: str) -> date:
    """解析日期字符串，失败返回今天"""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return date.today()


def _parse_query_date(date_str: str, today: date) -> date:
    """解析查询日期（date 参数）：绝对/相对表达 → 具体日期；失败回退今天并告警。

    Router 可能把用户消息里的时间词原样填进 date（"下周"），也可能直接填
    绝对日期。相对表达由确定性 _time_parser 解析——绝不让 LLM 心算日期。
    """
    if not date_str or not date_str.strip():
        return today
    parsed = parse_query_date(date_str, today)
    if parsed is not None:
        return parsed
    logger.warning(f"date 参数无法解析，回退今天: {date_str!r}")
    return today


# ── ToolSpec: birth_chart ───────────────────────────────────

BIRTH_CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "birth_date": {
            "type": "string",
            "description": "出生日期，YYYY-MM-DD",
        },
        "birth_time": {
            "type": "string",
            "description": "出生时间，HH:MM。如不填默认正午12:00，此时无法准确计算上升星座和宫位。",
        },
        "birth_place": {
            "type": "string",
            "description": "出生地点（城市名），用于更精确的时区换算，当前版本暂未启用。",
        },
    },
    "required": ["birth_date"],
}


class BirthChartTool(ToolSpec):
    """生成完整本命星盘。"""

    def __init__(self):
        super().__init__(
            tool_id="birth_chart",
            display_name="本命星盘",
            description="根据出生日期和时间生成完整本命星盘，包含太阳/月亮/上升星座、十大行星的星座位置、12宫位分布和行星相位关系。",
            schema=BIRTH_CHART_SCHEMA,
        )

    def validate_params(self, params: dict) -> list[str]:
        if not params.get("birth_date"):
            return ["birth_date"]
        return []

    async def execute(self, params: dict, ctx: ExecutionContext) -> ToolResult:
        _step_log("══════ birth_chart 开始执行 ══════", session=ctx.session_id)

        # ── Step 1: 解析输入 ──────────────────────
        birth_date_str = params.get("birth_date", "").strip()
        birth_time = params.get("birth_time", "").strip() or "12:00"
        birth_date = _parse_date(birth_date_str)
        _step_log("Step 1/5 输入解析",
                  birth_date=birth_date.isoformat(),
                  birth_time=birth_time,
                  raw_input=birth_date_str)

        # ── Step 2: 计算本命盘 ────────────────────
        _step_log("Step 2/5 本命盘计算...")
        chart = compute_natal_chart(birth_date, birth_time)

        # ── Step 3: 组装输出 ──────────────────────
        _step_log("Step 3/5 组装星盘数据...")

        sun_sign = ZODIAC_SIGNS[chart.sun_sign]
        moon_sign = ZODIAC_SIGNS[chart.moon_sign]
        asc_sign = ZODIAC_SIGNS[chart.ascendant_sign]

        # 行星位置
        planets_output = []
        for planet_id in ["sun", "moon", "mercury", "venus", "mars",
                          "jupiter", "saturn", "uranus", "neptune", "pluto"]:
            sign_id, deg = chart.planet_positions[planet_id]
            planet = PLANETS[planet_id]
            house = chart.planet_houses.get(planet_id, 0)
            dignity = get_planet_dignity(planet_id, sign_id)
            planets_output.append({
                "planet": planet.name,
                "symbol": planet.symbol,
                "sign": ZODIAC_SIGNS[sign_id].name,
                "sign_symbol": ZODIAC_SIGNS[sign_id].symbol,
                "degree": deg,
                "house": house,
                "house_name": HOUSES[house].name if house else "未知",
                "dignity": dignity,
            })

        # 宫位
        houses_output = []
        for h_num in range(1, 13):
            sign_id, cusp_lon, mid_lon = chart.houses[h_num]
            house_info = HOUSES[h_num]
            # 找出该宫位内的行星
            planets_in_house = [
                PLANETS[pid].name for pid, h in chart.planet_houses.items() if h == h_num
            ]
            houses_output.append({
                "number": h_num,
                "name": house_info.name,
                "area": house_info.area,
                "sign": ZODIAC_SIGNS[sign_id].name,
                "sign_symbol": ZODIAC_SIGNS[sign_id].symbol,
                "planets_in": planets_in_house,
            })

        # 相位
        aspects_output = []
        for aspect in chart.aspects:
            aspect_def = ASPECT_TYPES[aspect.aspect_type]
            aspects_output.append({
                "planet1": PLANETS[aspect.planet1].name,
                "symbol1": PLANETS[aspect.planet1].symbol,
                "planet2": PLANETS[aspect.planet2].name,
                "symbol2": PLANETS[aspect.planet2].symbol,
                "aspect": aspect_def.name,
                "angle": aspect.angle_actual,
                "orb": aspect.orb,
                "nature": aspect.nature,
            })

        # ── Step 4: Trace ─────────────────────────
        _step_log("Step 4/5 生成执行 trace...")
        trace_lines = [
            f"执行: birth_chart(birth_date={birth_date}, birth_time={birth_time})",
            f"太阳: {sun_sign.symbol}{sun_sign.name} | 月亮: {moon_sign.symbol}{moon_sign.name} | 上升: {asc_sign.symbol}{asc_sign.name}",
            f"行星数: {len(planets_output)} | 宫位数: {len(houses_output)} | 相位数: {len(aspects_output)}",
        ]

        # ── Step 5: 返回 ──────────────────────────
        _step_log("Step 5/5 返回星盘结果",
                  sun=sun_sign.name, moon=moon_sign.name, asc=asc_sign.name,
                  planets=len(planets_output), houses=len(houses_output),
                  aspects=len(aspects_output))

        return ToolResult(
            tool_id=self.tool_id,
            success=True,
            output={
                "birth_date": birth_date.isoformat(),
                "birth_time": birth_time,
                "sun_sign": f"{sun_sign.symbol} {sun_sign.name}",
                "moon_sign": f"{moon_sign.symbol} {moon_sign.name}",
                "ascendant": f"{asc_sign.symbol} {asc_sign.name} (上升)",
                "sun_traits": sun_sign.sun_description,
                "moon_traits": moon_sign.moon_description,
                "rising_traits": asc_sign.rising_description,
                "planets": planets_output,
                "houses": houses_output,
                "aspects": aspects_output,
            },
            trace="\n".join(trace_lines),
        )


# ── ToolSpec: daily_transit ─────────────────────────────────

DAILY_TRANSIT_SCHEMA = {
    "type": "object",
    "properties": {
        "birth_date": {
            "type": "string",
            "description": "出生日期，YYYY-MM-DD",
        },
        "birth_time": {
            "type": "string",
            "description": "出生时间 HH:MM，不填默认 12:00",
        },
        "date": {
            "type": "string",
            "description": "要查询的日期 YYYY-MM-DD，不填默认今天",
        },
    },
    "required": ["birth_date"],
}


class DailyTransitTool(ToolSpec):
    """计算今日流年星象 vs 本命盘的交互。"""

    def __init__(self):
        super().__init__(
            tool_id="daily_transit",
            display_name="流年星象",
            description="根据出生日期计算今日流年星象（Transits），展示当前行星运行与你本命盘的交互，包括形成的相位、影响的宫位及其占星含义。",
            schema=DAILY_TRANSIT_SCHEMA,
        )

    def validate_params(self, params: dict) -> list[str]:
        if not params.get("birth_date"):
            return ["birth_date"]
        return []

    async def execute(self, params: dict, ctx: ExecutionContext) -> ToolResult:
        _step_log("══════ daily_transit 开始执行 ══════", session=ctx.session_id)

        # ── Step 1: 解析输入 ──────────────────────
        birth_date = _parse_date(params.get("birth_date", ""))
        birth_time = params.get("birth_time", "").strip() or "12:00"
        query_date = _parse_query_date(
            params.get("date", "").strip(), date.today()
        )
        _step_log("Step 1/6 输入解析",
                  birth_date=birth_date.isoformat(), birth_time=birth_time,
                  query_date=query_date.isoformat())

        # ── Step 2: 生成本命盘 ────────────────────
        _step_log("Step 2/6 生成本命盘...")
        chart = compute_natal_chart(birth_date, birth_time)

        # ── Step 3: 计算流年星象 ──────────────────
        _step_log("Step 3/6 计算流年星象 Transits...")
        natal_positions = {
            pid: compute_natal_longitude(chart, pid)
            for pid in PLANETS
        }
        transits = compute_transits(natal_positions, query_date)

        # ── Step 4: 生成运势解读数据 ──────────────
        _step_log("Step 4/6 生成运势解读...")
        horoscope = interpret_transits_for_horoscope(transits, chart)

        # ── Step 5: 组装输出 ──────────────────────
        _step_log("Step 5/6 组装流年结果...")

        transit_aspects_out = []
        for t in transits:
            aspect_def = ASPECT_TYPES[t.aspect_type]
            transit_aspects_out.append({
                "transit_planet": f"{PLANETS[t.transit_planet].symbol} {PLANETS[t.transit_planet].name}",
                "natal_planet": f"{PLANETS[t.natal_planet].symbol} {PLANETS[t.natal_planet].name}",
                "aspect": aspect_def.name,
                "angle": t.angle_actual,
                "orb": t.orb,
                "nature": aspect_def.nature,
                "impact": t.impact_level,
                "transit_sign": ZODIAC_SIGNS[t.transit_sign].name,
                "natal_sign": ZODIAC_SIGNS[t.natal_sign].name,
            })

        # Trace
        trace_lines = [
            f"执行: daily_transit(birth_date={birth_date}, query_date={query_date})",
            f"本命: ☉{ZODIAC_SIGNS[chart.sun_sign].name} ☽{ZODIAC_SIGNS[chart.moon_sign].name} ↑{ZODIAC_SIGNS[chart.ascendant_sign].name}",
            f"流年相位: {len(transits)} 个 (和谐={horoscope['harmony_count']} 挑战={horoscope['challenge_count']})",
        ]

        # ── Step 6: 返回 ──────────────────────────
        _step_log("Step 6/6 返回流年结果",
                  total_transits=len(transits),
                  overall=horoscope["overall"]["level"],
                  love=horoscope["love"]["level"],
                  work=horoscope["work"]["level"],
                  health=horoscope["health"]["level"])

        return ToolResult(
            tool_id=self.tool_id,
            success=True,
            output={
                "birth_date": birth_date.isoformat(),
                "query_date": query_date.isoformat(),
                "sun_sign": f"{ZODIAC_SIGNS[chart.sun_sign].symbol} {ZODIAC_SIGNS[chart.sun_sign].name}",
                "moon_sign": f"{ZODIAC_SIGNS[chart.moon_sign].symbol} {ZODIAC_SIGNS[chart.moon_sign].name}",
                "ascendant": f"{ZODIAC_SIGNS[chart.ascendant_sign].symbol} {ZODIAC_SIGNS[chart.ascendant_sign].name}",
                "transit_aspects_count": len(transits),
                "transit_aspects": transit_aspects_out,
                "horoscope": horoscope,
            },
            trace="\n".join(trace_lines),
        )


# ── ToolSpec: horoscope_daily ───────────────────────────────

HOROSCOPE_DAILY_SCHEMA = {
    "type": "object",
    "properties": {
        "sign": {
            "type": "string",
            "description": "星座名称（如'白羊座'），用于提取星座基本信息。如果同时提供 birth_date，则进行完整流年计算。",
        },
        "birth_date": {
            "type": "string",
            "description": "出生日期 YYYY-MM-DD。如果提供，则计算个性化流年运势；不提供则给出该星座的通用运势。",
        },
        "birth_time": {
            "type": "string",
            "description": "出生时间 HH:MM，配合 birth_date 使用",
        },
        "date": {
            "type": "string",
            "description": "要查询的日期 YYYY-MM-DD。用户说'下周/明天/这周/周一'等时间时，填入对应日期；不填默认今天。",
        },
    },
    "required": [],
}


class HoroscopeDailyTool(ToolSpec):
    """每日星座运势——支持通用运势和个性化流年运势两种模式。"""

    def __init__(self):
        super().__init__(
            tool_id="horoscope_daily",
            display_name="每日星座运势",
            description="查询星座今日运势。如果提供出生日期，则基于本命盘和流年星象精确计算；如果只提供星座名，则给出该星座基于当前行星位置的通用运势。支持指定日期（date 参数），如'下周运势'会按对应日期计算。",
            schema=HOROSCOPE_DAILY_SCHEMA,
        )

    def validate_params(self, params: dict) -> list[str]:
        # 至少需要 sign 或 birth_date 之一
        if not params.get("sign") and not params.get("birth_date"):
            return ["sign 或 birth_date"]
        return []

    async def execute(self, params: dict, ctx: ExecutionContext) -> ToolResult:
        _step_log("══════ horoscope_daily 开始执行 ══════", session=ctx.session_id)

        sign_input = params.get("sign", "").strip()
        birth_date_str = params.get("birth_date", "").strip()
        birth_time = params.get("birth_time", "").strip() or "12:00"
        today = date.today()
        query_date = _parse_query_date(params.get("date", "").strip(), today)

        _step_log("Step 1/4 输入解析",
                  sign=sign_input, birth_date=birth_date_str,
                  birth_time=birth_time, today=today.isoformat(),
                  query_date=query_date.isoformat())

        # ── 有出生日期 → 完整流年运势 ─────────────
        if birth_date_str:
            _step_log("Step 2/4 完整流年模式（有 birth_date）")
            birth_date = _parse_date(birth_date_str)
            chart = compute_natal_chart(birth_date, birth_time)

            natal_positions = {
                pid: compute_natal_longitude(chart, pid)
                for pid in PLANETS
            }
            transits = compute_transits(natal_positions, query_date)
            horoscope = interpret_transits_for_horoscope(transits, chart)

            sun_sign = ZODIAC_SIGNS[chart.sun_sign]

            trace_lines = [
                f"执行: horoscope_daily(birth_date={birth_date}, query_date={query_date}, mode=full_transit)",
                f"本命: ☉{sun_sign.name} ☽{ZODIAC_SIGNS[chart.moon_sign].name} ↑{ZODIAC_SIGNS[chart.ascendant_sign].name}",
                f"流年({query_date}): {len(transits)} 相位 | 综合={horoscope['overall']['level']}",
            ]

            _step_log("Step 4/4 返回完整流年运势",
                      sun=sun_sign.name, query_date=query_date.isoformat(),
                      overall=horoscope["overall"]["level"])

            return ToolResult(
                tool_id=self.tool_id,
                success=True,
                output={
                    "mode": "personalized_transit",
                    "date": query_date.isoformat(),
                    "sun_sign": f"{sun_sign.symbol} {sun_sign.name}",
                    "moon_sign": f"{ZODIAC_SIGNS[chart.moon_sign].symbol} {ZODIAC_SIGNS[chart.moon_sign].name}",
                    "ascendant": f"{ZODIAC_SIGNS[chart.ascendant_sign].symbol} {ZODIAC_SIGNS[chart.ascendant_sign].name}",
                    "sun_traits": sun_sign.sun_description,
                    "moon_traits": ZODIAC_SIGNS[chart.moon_sign].moon_description,
                    "rising_traits": ZODIAC_SIGNS[chart.ascendant_sign].rising_description,
                    "overall": horoscope["overall"],
                    "love": horoscope["love"],
                    "work": horoscope["work"],
                    "health": horoscope["health"],
                    "total_transits": len(transits),
                    "harmony_count": horoscope["harmony_count"],
                    "challenge_count": horoscope["challenge_count"],
                    "key_transits": horoscope["key_transits"],
                },
                trace="\n".join(trace_lines),
            )

        # ── 只有星座 → 基于签名信息的通用运势 ─────
        _step_log("Step 2/4 通用运势模式（仅有星座名）")

        sign_id = resolve_sign(sign_input)
        if sign_id is None:
            _step_log("Step 3/4 星座解析失败", sign_input=sign_input)
            return ToolResult(
                tool_id=self.tool_id,
                success=False,
                error=f"无法识别星座 '{sign_input}'。支持的星座: {', '.join(s.name for s in ZODIAC_SIGNS.values())}",
            )

        sign_info = ZODIAC_SIGNS[sign_id]

        # 计算查询日太阳在哪个星座 → 作为运势基调参考
        sun_lon_today = _engine_compute_sun_lon(query_date)
        sun_sign_today = _engine_longitude_to_sign(sun_lon_today)

        _step_log("Step 3/4 通用运势生成",
                  sign=sign_info.name, element=sign_info.element.value,
                  modality=sign_info.modality.value,
                  query_date=query_date.isoformat(),
                  sun_in=ZODIAC_SIGNS[sun_sign_today].name)

        # 简单运势生成
        from app.domain_packs.metacare._astrology_engine import compute_planet_longitude
        venus_lon = compute_planet_longitude("venus", query_date)
        mars_lon = compute_planet_longitude("mars", query_date)
        venus_sign = _engine_longitude_to_sign(venus_lon)
        mars_sign = _engine_longitude_to_sign(mars_lon)

        # 金星位置影响爱情运
        if venus_sign == sign_id:
            love_level, love_text = "⭐⭐⭐ 旺", f"金星正经过你的星座，爱情运势明显提升。你的魅力值达到近期高点，适合表达心意和社交活动。"
        elif ZODIAC_SIGNS[venus_sign].element == sign_info.element:
            love_level, love_text = "⭐⭐ 平", f"金星在同元素星座{venus_sign}，感情方面虽无惊喜但也平稳舒适，适合维护现有关系。"
        else:
            love_level, love_text = "⭐ 弱", f"金星当前在{ZODIAC_SIGNS[venus_sign].name}，与你的星座能量不太契合。感情上建议多一些耐心和理解。"

        # 火星位置影响行动力
        if mars_sign == sign_id:
            work_level, work_text = "⭐⭐⭐ 旺", f"火星正经过你的星座，行动力和决断力爆棚。该日适合推进重要项目和做出关键决策。"
        elif ZODIAC_SIGNS[mars_sign].element == sign_info.element:
            work_level, work_text = "⭐⭐ 平", f"火星在同元素星座{mars_sign}，工作节奏平稳，按计划推进即可。"
        else:
            work_level, work_text = "⭐ 弱", f"火星当前在{ZODIAC_SIGNS[mars_sign].name}，可能需要更多耐心来推动工作。不妨把重点放在整理和规划上。"

        # 综合运势
        sun_same = (sun_sign_today == sign_id)
        if sun_same:
            overall_level = "⭐⭐⭐ 旺"
            overall_text = f"太阳正经过你的星座，整体能量充盈，各方面运势都在高位。"
        else:
            overall_level = "⭐⭐ 平"
            overall_text = f"太阳当前在{ZODIAC_SIGNS[sun_sign_today].name}。作为{sign_info.element.value}象{sign_info.modality.value}星座，该日适合{f'发挥你的{sign_info.sun_traits[0]}特质' if sign_info.sun_traits else '按日常节奏推进'}。"

        trace_lines = [
            f"执行: horoscope_daily(sign={sign_id}, query_date={query_date}, mode=general)",
            f"查询日 {query_date}: 太阳在{ZODIAC_SIGNS[sun_sign_today].name} | 金星在{ZODIAC_SIGNS[venus_sign].name} | 火星在{ZODIAC_SIGNS[mars_sign].name}",
            f"综合={overall_level} 爱情={love_level} 事业={work_level}",
        ]

        _step_log("Step 4/4 返回通用运势",
                  overall=overall_level, love=love_level, work=work_level,
                  query_date=query_date.isoformat())

        return ToolResult(
            tool_id=self.tool_id,
            success=True,
            output={
                "mode": "general",
                "date": query_date.isoformat(),
                "sign": sign_info.name,
                "symbol": sign_info.symbol,
                "element": sign_info.element.value,
                "modality": sign_info.modality.value,
                "ruler": sign_info.ruler,
                "sun_sign_traits": sign_info.sun_description,
                "moon_sign_traits": sign_info.moon_description,
                "current_sun_in": ZODIAC_SIGNS[sun_sign_today].name,
                "current_venus_in": ZODIAC_SIGNS[venus_sign].name,
                "current_mars_in": ZODIAC_SIGNS[mars_sign].name,
                "overall": {"level": overall_level, "text": overall_text},
                "love": {"level": love_level, "text": love_text},
                "work": {"level": work_level, "text": work_text},
                "health": {"level": "⭐⭐ 平", "text": f"作为{sign_info.element.value}象星座，注意{sign_info.body_part}的保养。保持规律作息即可。"},
            },
            trace="\n".join(trace_lines),
        )


# ── 内部辅助 ────────────────────────────────────────────────

def compute_natal_longitude(chart, planet_id: str) -> float:
    """从 NatalChart 中恢复行星的绝对经度"""
    sign_id, deg_in_sign = chart.planet_positions[planet_id]
    sign_index = list(ZODIAC_SIGNS.keys()).index(sign_id)
    return sign_index * 30.0 + deg_in_sign


def _engine_compute_sun_lon(d: date) -> float:
    from app.domain_packs.metacare._astrology_engine import compute_planet_longitude
    return compute_planet_longitude("sun", d)


def _engine_longitude_to_sign(lon: float) -> str:
    from app.domain_packs.metacare._astrology_engine import longitude_to_sign
    return longitude_to_sign(lon)
