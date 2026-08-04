"""
LLM 驱动的用户画像提取器。

在 MemoryService.ingest 中异步调用，不阻塞主请求路径。
通过 LLM 结构化输出精准判断用户是否在自述个人信息。
"""

import json
import logging
import re

from app.llm.llm_client import LLMClient, LLMCallConfig, LLMCallResult

logger = logging.getLogger("mysu.profile_extractor")


PROFILE_EXTRACT_PROMPT = """你是一个严格的信息提取器。唯一任务：判断用户是否在声明**自己的**个人信息。

核心规则（违反则完全错误）：
- 用户只是在查询/打听某个信息 → 返回 {}
- 用户明确在说自己 → 提取对应字段

应该提取的例子（用户在自述）：
- "我是白羊座" → {"zodiac_sign": "aries"}
- "我生日1995年6月15日" → {"birth_date": "1995-06-15"}
- "我叫小明，天蝎座" → {"name": "小明", "zodiac_sign": "scorpio"}
- "我1995年的，下午2点半生的" → {"birth_date": "1995-??-??", "birth_time": "14:30"}

绝对不能提取的例子（用户在打听/查询）：
- "看看白羊座今天的运势" → {} （打听，非自述）
- "摩羯座今日运程怎样" → {} （查询，非自述）
- "双子座和天蝎座配吗" → {} （讨论配对）
- "1995年6月15日出生的是什么星座" → {} （问日期对应星座）

字段规范：
- birth_date: YYYY-MM-DD，只提取具体到月日的日期
- birth_time: HH:MM 24小时制（下午2点半=14:30）
- zodiac_sign: 英文ID，仅当用户说"我是XX座"时填写
  白羊=aries 金牛=taurus 双子=gemini 巨蟹=cancer
  狮子=leo 处女=virgo 天秤=libra 天蝎=scorpio
  射手=sagittarius 摩羯=capricorn 水瓶=aquarius 双鱼=pisces
- 只输出有值的字段。无任何个人信息 → {}"""


PROFILE_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "birth_date": {
            "type": "string",
            "description": "出生日期 YYYY-MM-DD"
        },
        "birth_time": {
            "type": "string",
            "description": "出生时间 HH:MM 24小时制"
        },
        "zodiac_sign": {
            "type": "string",
            "enum": [
                "aries", "taurus", "gemini", "cancer",
                "leo", "virgo", "libra", "scorpio",
                "sagittarius", "capricorn", "aquarius", "pisces"
            ],
            "description": "仅当用户说'我是XX座'时填写。查询/打听则绝对不填。"
        },
        "gender": {
            "type": "string",
            "enum": ["male", "female"],
        },
        "name": {
            "type": "string",
            "description": "用户自报的名字"
        },
    },
}

# 预过滤器
_PRE_FILTER = re.compile(
    r"\d{4}|下午|上午|早上|晚上|凌晨"
    r"|白羊|金牛|双子|巨蟹|狮子|处女|天秤|天蝎|射手|摩羯|水瓶|双鱼"
    r"|我是|我叫|我的|我生日|我出生于"
    r"|[点半整]|:\d{2}|男生|女生|男的|女的"
)


def _should_extract(message: str) -> bool:
    return bool(_PRE_FILTER.search(message))


def _is_valid_date(value: str) -> bool:
    """校验日期格式 YYYY-MM-DD"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))


def _is_valid_time(value: str) -> bool:
    """校验时间格式 HH:MM"""
    return bool(re.match(r"^\d{2}:\d{2}$", value))


class ProfileExtractor:
    """LLM 驱动的用户画像提取器。"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(
        self, user_message: str, allow_bare: bool = False
    ) -> dict:
        # ── 前置过滤：regex 快速判断是否可能是自指 ──
        # 宽松模式（allow_bare=True）跳过自指检查——
        # 用于用户在澄清回答中直接给出"1995年6月15日"这类裸信息。
        if not allow_bare:
            from app.memory.memory_service import _has_self_reference
            if not _has_self_reference(user_message):
                logger.debug(f"画像提取跳过（非自指）: {user_message[:50]}")
                return {}

        # 也检查预过滤器（是否包含个人信息关键词）
        if not _should_extract(user_message):
            logger.debug(f"画像提取跳过（无个人信息关键词）: {user_message[:50]}")
            return {}

        logger.info(f"画像提取 LLM: {user_message[:80]}")

        try:
            result: LLMCallResult = await self.llm.call(
                LLMCallConfig(
                    system_prompt=PROFILE_EXTRACT_PROMPT,
                    user_prompt=f"用户消息：{user_message}",
                    response_format=PROFILE_EXTRACT_SCHEMA,
                    max_tokens=200,
                    temperature=0.0,
                    call_type="ingest",
                )
            )

            if result.structured_output:
                valid_keys = {"birth_date", "birth_time", "zodiac_sign",
                              "gender", "name"}
                filtered = {}
                for k, v in result.structured_output.items():
                    if k not in valid_keys or not v:
                        continue
                    # 校验值格式
                    if k == "birth_date" and not _is_valid_date(v):
                        continue
                    if k == "birth_time" and not _is_valid_time(v):
                        continue
                    # name 必须 ≥2 字符且不是无意义词（如把"我是"误当名字）
                    if k == "name" and (len(str(v)) < 2 or str(v) in ("我是", "我叫")):
                        continue
                    filtered[k] = v
                if filtered:
                    logger.info(
                        f"画像提取: {filtered} "
                        f"(tokens_in={result.tokens_in} tokens_out={result.tokens_out})"
                    )
                else:
                    logger.info(f"画像提取: 未发现个人信息")
                return filtered
            else:
                return {}

        except Exception as e:
            logger.error(f"画像提取 LLM 失败: {e}")
            return {}
