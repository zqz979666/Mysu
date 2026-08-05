"""确定性时间解析——把相对时间表达解析为具体日期。

与整体架构一致（LLM 只做意图解析，确定性引擎算结果）：
Router 把用户消息里的时间词原样填进 date 参数（或填绝对日期），
本模块是日期计算的权威来源——纯规则、零 LLM、可单测。

支持表达：
- 绝对日期：YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日 / M月D日 / YYYYMMDD
- 相对日期：今天/今日、明天/明日、后天、大后天、N天后
- 周表达：下周/下星期/下礼拜（→下周一）、下周X、这周/本周（→本周一）、
  这周X/本周X、周X/星期X/礼拜X、上周X
- 兜底：返回 None（调用方决定回退策略，绝不静默用错日期）
"""

import re
from datetime import date, timedelta

# 中文星期名 → weekday() 值（0=周一 ... 6=周日）
_WEEKDAY_CN: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

# 绝对日期（多格式）
_RE_ABS_DATE = re.compile(
    r"(?P<y>\d{4})\s*[年/\-]\s*(?P<m>\d{1,2})\s*[月/\-]\s*(?P<d>\d{1,2})"
    r"|(?P<yy>\d{4})(?P<mm>\d{2})(?P<dd>\d{2})"
    r"|(?P<mm2>\d{1,2})\s*月\s*(?P<dd2>\d{1,2})\s*日?"
)

# 周表达（注意顺序：具体的"下周X"先于泛指的"下周"）
_RE_NEXT_WEEKDAY = re.compile(r"下(?:周|星期|礼拜)([一二三四五六日天])")
_RE_THIS_WEEKDAY = re.compile(r"(?:这|本)?(?:周|星期|礼拜)([一二三四五六日天])")
_RE_LAST_WEEKDAY = re.compile(r"上(?:周|星期|礼拜)([一二三四五六日天])")
_RE_DAYS_LATER = re.compile(r"(\d+)\s*天(?:后|以后|之后)")


def _monday_of(d: date) -> date:
    """包含 d 的那一周的周一"""
    return d - timedelta(days=d.weekday())


def _next_weekday(base: date, wd: int) -> date:
    """base 所在周起，第一个星期 wd（含 base 当天）"""
    return base + timedelta(days=(wd - base.weekday()) % 7)


def _parse_absolute(text: str) -> date | None:
    m = _RE_ABS_DATE.search(text)
    if not m:
        return None
    try:
        if m.group("y"):
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if m.group("yy"):
            return date(int(m.group("yy")), int(m.group("mm")), int(m.group("dd")))
        if m.group("mm2"):
            y = date.today().year
            return date(y, int(m.group("mm2")), int(m.group("dd2")))
    except ValueError:
        return None
    return None


def parse_query_date(text: str, today: date | None = None) -> date | None:
    """从文本中解析查询日期。

    Args:
        text: Router 填的 date 参数值或用户原始消息片段
        today: 基准日（测试可注入），默认真实今天

    Returns:
        解析到的日期；无法解析返回 None（调用方回退，不得静默用错日期）
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    today = today or date.today()

    # 1. 绝对日期优先（"2026-08-12"、"8月12日"）
    abs_d = _parse_absolute(t)
    if abs_d is not None:
        return abs_d

    # 2. 相对日期（"大后天"先于"后天"，避免子串误匹配）
    if re.search(r"大后天", t):
        return today + timedelta(days=3)
    if re.search(r"后天", t):
        return today + timedelta(days=2)
    if re.search(r"明天|明日", t):
        return today + timedelta(days=1)
    if re.search(r"今天|今日", t):
        return today

    # 3. N天后
    m = _RE_DAYS_LATER.search(t)
    if m:
        return today + timedelta(days=int(m.group(1)))

    this_monday = _monday_of(today)

    # 4. 上周X → 上周一 + offset
    m = _RE_LAST_WEEKDAY.search(t)
    if m:
        return this_monday - timedelta(days=7) + timedelta(days=_WEEKDAY_CN[m.group(1)])

    # 5. 下周X → 下周一 + offset
    m = _RE_NEXT_WEEKDAY.search(t)
    if m:
        return this_monday + timedelta(days=7) + timedelta(days=_WEEKDAY_CN[m.group(1)])

    # 6. 下周（泛指）→ 下周一
    if re.search(r"下(?:周|星期|礼拜)", t):
        return this_monday + timedelta(days=7)

    # 7. 这周X / 本周X / 周X / 星期X → 本周
    m = _RE_THIS_WEEKDAY.search(t)
    if m:
        return this_monday + timedelta(days=_WEEKDAY_CN[m.group(1)])

    # 8. 这周/本周（泛指）→ 本周一
    if re.search(r"这周|本周", t):
        return this_monday

    return None
