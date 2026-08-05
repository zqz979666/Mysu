"""
LLM 驱动的用户画像提取器。

在 MemoryService.ingest 中异步调用，不阻塞主请求路径。
核心原则：**LLM 全权判断**——不做任何规则预判（自指检测/关键词过滤），
让 LLM 看完整消息自行决定用户是否在自述、提取哪些字段。

保留的仅有两类确定性兜底（不参与判断，只做防御）：
1. expect_fields：澄清上下文提示（告知 LLM 用户在回答哪个询问）
2. 输出值格式校验：拒绝 LLM 吐出的垃圾值（"?"、"我是"等）
"""

import logging
import re

from app.llm.llm_client import LLMClient, LLMCallConfig, LLMCallResult

logger = logging.getLogger("mysu.profile_extractor")


PROFILE_EXTRACT_PROMPT = """你是一个严格的信息提取器。唯一任务：判断用户是否在声明**自己的**个人信息。

核心规则（违反则完全错误）：
- 用户只是在查询/打听某个信息 → 返回 {}
- 用户明确在说自己 → 提取对应字段
- **当用户说出"我是XX座/我的生日是XX/我叫XX"这类明确自述时，必须提取对应字段，这是命令**——不要因为消息里还有其他内容就跳过
- **严禁**把"用户""消息""用户消息"这类标签词当作名字提取
- **他人信息绝不提取**：用户提到"他/她/我朋友/我同事/我女儿/我老婆/帮我朋友算"等 → 那是别人的信息，返回 {}
  - "帮我算下我朋友的运势，他是白羊座" → {}（白羊座是朋友的）
  - "我朋友是双子座，帮我看看" → {}（说的是别人）

应该提取的例子（用户在自述，必须带"我/我的"）：
- "我是白羊座" → {"zodiac_sign": "aries"}
- "我生日1995年6月15日" → {"birth_date": "1995-06-15"}
- "我叫小明，天蝎座" → {"name": "小明", "zodiac_sign": "scorpio"}
- "我1995年的，下午2点半生的" → {"birth_date": "1995-??-??", "birth_time": "14:30"}

绝对不能提取的例子（用户在打听/转述他人）：
- "看看白羊座今天的运势" → {} （打听，非自述）
- "摩羯座今日运程怎样" → {} （查询，非自述）
- "双子座和天蝎座配吗" → {} （讨论配对）
- "1995年6月15日出生的是什么星座" → {} （问日期对应星座）
- "我朋友是双子座，帮我看看" → {} （说的是别人）
- "他是白羊座" / "她生日是1995年" → {} （第三人称，非用户自己）

字段规范：
- birth_date: YYYY-MM-DD，只提取具体到月日的日期
- birth_time: HH:MM 24小时制（下午2点半=14:30，不是14:00）
- zodiac_sign: 英文ID，仅当用户说"我是XX座"时填写
  白羊=aries 金牛=taurus 双子=gemini 巨蟹=cancer
  狮子=leo 处女=virgo 天秤=libra 天蝎=scorpio
  射手=sagittarius 摩羯=capricorn 水瓶=aquarius 双鱼=pisces
- name: 只有用户说了自己的真实姓名/昵称时才填（如"我叫小明"）
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


def _is_valid_date(value: str) -> bool:
    """校验日期格式 YYYY-MM-DD"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))


def _is_valid_time(value: str) -> bool:
    """校验时间格式 HH:MM"""
    return bool(re.match(r"^\d{2}:\d{2}$", value))


# ── 澄清参数提取（与画像提取解耦）─────────────────
# 澄清 = 工具参数补全：按缺失字段动态提取，结果只用于本次执行，不落库画像。
# 画像 = 用户记忆沉淀：ingest 里 LLM 判断自述，落库 user_profiles。

_CLARIFY_FIELD_SPLIT = re.compile(r"[或,，/、\s]+")


def _build_clarify_schema(missing: list[str]) -> dict:
    """从缺失描述生成动态提取 schema（字段名做轻清洗）。"""
    fields: set[str] = set()
    for m in missing:
        cleaned = m.replace("缺少参数:", "").strip()
        for part in _CLARIFY_FIELD_SPLIT.split(cleaned):
            part = part.strip()
            if part and part not in ("缺少参数", "或"):
                fields.add(part)
    return {
        "type": "object",
        "properties": {f: {"type": "string"} for f in sorted(fields)},
    }


CLARIFY_EXTRACT_PROMPT = """你是一个参数提取器。用户在回答系统之前的询问，系统需要补充一些信息。

从用户的回答中提取这些信息的值，输出 JSON 对象。
规则：
- 只输出用户在回答中明确给出的字段
- 未提到的字段不要输出，不要编造
- 日期统一为 YYYY-MM-DD，时间统一为 HH:MM（24小时制，下午2点半=14:30）
- 只输出数据，不要输出 schema 定义本身"""


async def extract_clarify_params(
    llm_client: "LLMClient",
    user_answer: str,
    missing: list[str],
) -> dict:
    """从澄清回答中提取缺失的参数值（动态 schema，支持任意字段）。

    与画像提取完全独立：结果仅用于本次工具执行参数补全。
    是否落库画像由 ingest 里的画像提取器单独判断。
    """
    schema = _build_clarify_schema(missing)
    if not schema["properties"]:
        return {}

    try:
        result: LLMCallResult = await llm_client.call(
            LLMCallConfig(
                system_prompt=CLARIFY_EXTRACT_PROMPT,
                user_prompt=(
                    f"系统需要补充的信息：{'、'.join(missing)}\n\n"
                    f"用户的回答：{user_answer}"
                ),
                response_format=schema,
                max_tokens=200,
                temperature=0.0,
                call_type="clarify",
            )
        )
        out = result.structured_output or {}
        # 只保留 schema 内的字段，且值非空
        valid = {k: v for k, v in out.items()
                 if k in schema["properties"] and v}
        if valid:
            logger.info(f"澄清参数提取: {valid}")
        else:
            logger.info("澄清参数提取: 未提取到有效参数")
        return valid
    except Exception as e:
        logger.error(f"澄清参数提取失败: {e}")
        return {}


class ProfileExtractor:
    """LLM 驱动的用户画像提取器——零规则预判，LLM 全权判断。"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(
        self,
        user_message: str,
    ) -> dict:
        """即时画像提取——只处理无歧义的强自指（"我是/我的"）。

        注意（USER-DIRECTED）：不再接收 expect_fields。历史版本会把
        "用户在回答澄清 → 回答中的日期/星座视为用户自己的信息"注入 prompt，
        导致用户替他人询问时（"帮我朋友算，他是白羊座"）把星座写进用户画像。
        澄清回答的画像归属由会话级提炼（extract_session_memory）用全量
        对话上下文判断；这里只信"我/我的"。
        """

        logger.info(f"画像提取 LLM: {user_message[:80]}")

        try:
            result: LLMCallResult = await self.llm.call(
                LLMCallConfig(
                    system_prompt=PROFILE_EXTRACT_PROMPT,
                    user_prompt=f"待提取的文本：{user_message}",
                    response_format=PROFILE_EXTRACT_SCHEMA,
                    max_tokens=200,
                    temperature=0.0,
                    call_type="ingest",
                )
            )

            if not result.structured_output:
                return {}

            # 防御性值校验：拒绝垃圾值（不参与"是否自述"判断）
            valid_keys = {"birth_date", "birth_time", "zodiac_sign",
                          "gender", "name"}
            filtered = {}
            for k, v in result.structured_output.items():
                if k not in valid_keys or not v:
                    continue
                if k == "birth_date" and not _is_valid_date(str(v)):
                    continue
                if k == "birth_time" and not _is_valid_time(str(v)):
                    continue
                # name 必须 ≥2 字符且不是无意义词（如把"我是"误当名字）
                if k == "name" and (
                    len(str(v)) < 2 or str(v) in ("我是", "我叫", "用户")
                ):
                    continue
                filtered[k] = v
            if filtered:
                logger.info(
                    f"画像提取: {filtered} "
                    f"(tokens_in={result.tokens_in} tokens_out={result.tokens_out})"
                )
            else:
                logger.info("画像提取: 未发现个人信息")
            return filtered

        except Exception as e:
            logger.error(f"画像提取 LLM 失败: {e}")
            return {}


# ── 会话级记忆提炼（session 结束后全量判断）──────────────
# USER-DIRECTED 设计：用户替他人询问时（"帮我朋友算，他是白羊座"），
# 单条消息的即时提取无法判断归属。会话级提炼读全量对话上下文，
# 能区分"用户自述" vs "转述他人"，同时提炼长期事实与偏好。

SESSION_MEMORY_EXTRACT_PROMPT = """你是一个记忆提炼器。给定一段完整的用户与助手的对话记录，判断哪些信息值得长期记住。

输出三类记忆：

1. profile（用户画像）——用户**自己**的基本信息：
   - birth_date（YYYY-MM-DD）、birth_time（HH:MM 24小时制）、zodiac_sign（英文ID：aries/taurus/gemini/cancer/leo/virgo/libra/scorpio/sagittarius/capricorn/aquarius/pisces）、name（用户自称的名字）、gender
2. facts（长期事实）——用户的生活事件、偏好、关系，每项 {type, content}：
   - life_event: 生活事件（"最近在找工作"、"下个月搬家"）
   - preference: 偏好（"喜欢猫"、"不喜欢太长的回复"）
   - relationship: 关系/他人信息（"朋友是白羊座"、"有个妹妹在读大学"）
3. preferences（偏好设置）——沟通偏好键值对（如 {"reply_style": "简洁"}、{"language": "zh"}）

关键判断规则（违反则错误）：
- 归属判断是核心："我/我的/我是/我出生" → 用户自己的信息，写入 profile
- "他/她/我朋友/我同事/我女儿/我老婆/帮我朋友算/帮我闺蜜看" → **他人的信息**，绝不写入 profile，至多作为 relationship 事实
- **当对话里出现明确的关系陈述（"我朋友是白羊座""我有个妹妹在读大学"）时，应作为 relationship 事实记录**——这类信息对长期陪伴有价值
- 澄清回答要结合上下文判断归属：系统问"你的生日是？"用户答"1995年6月15日" → 用户自己的；
  用户主动说"帮我朋友算，他是白羊座" → 白羊座是朋友的，不写入 profile，但可记 relationship 事实
- 对话里反复出现的稳定偏好（多次表达）比一次性说法更值得记录
- 无法确定归属的信息 → 不提取
- 只输出有把握的内容，没有就省略，不要编造

输出严格 JSON：
{
  "profile": {},
  "facts": [],
  "preferences": {}
}"""

SESSION_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "profile": {
            "type": "object",
            "properties": {
                "birth_date": {"type": "string"},
                "birth_time": {"type": "string"},
                "zodiac_sign": {"type": "string"},
                "name": {"type": "string"},
                "gender": {"type": "string"},
            },
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["life_event", "preference", "relationship"],
                    },
                    "content": {"type": "string"},
                },
                "required": ["type", "content"],
            },
        },
        "preferences": {"type": "object"},
    },
    "required": ["profile", "facts", "preferences"],
}


async def extract_session_memory(
    llm_client: "LLMClient",
    transcript: str,
) -> dict:
    """从全量对话记录中提炼记忆（画像 + 长期事实 + 偏好）。

    由 MemoryService.extract_session_memory 在 session 结束后调用。

    Returns:
        {"profile": {...}, "facts": [...], "preferences": {...}}
    """
    try:
        result: LLMCallResult = await llm_client.call(
            LLMCallConfig(
                system_prompt=SESSION_MEMORY_EXTRACT_PROMPT,
                user_prompt=f"对话记录：\n{transcript}",
                response_format=SESSION_MEMORY_SCHEMA,
                max_tokens=500,
                temperature=0.0,
                call_type="memory_extract",
            )
        )
    except Exception as e:
        logger.error(f"会话记忆提炼 LLM 失败: {e}")
        return {"profile": {}, "facts": [], "preferences": {}}

    out = result.structured_output or {}
    if not isinstance(out, dict):
        return {"profile": {}, "facts": [], "preferences": {}}

    # ── 防御性校验（不参与归属判断，只拒绝垃圾值）──
    profile_raw = out.get("profile") or {}
    profile: dict = {}
    if isinstance(profile_raw, dict):
        for k, v in profile_raw.items():
            if k not in ("birth_date", "birth_time", "zodiac_sign", "name", "gender") or not v:
                continue
            if k == "birth_date" and not _is_valid_date(str(v)):
                continue
            if k == "birth_time" and not _is_valid_time(str(v)):
                continue
            if k == "name" and (len(str(v)) < 2 or str(v) in ("我是", "我叫", "用户")):
                continue
            profile[k] = v

    facts: list[dict] = []
    for f in out.get("facts") or []:
        if not isinstance(f, dict):
            continue
        ftype = f.get("type", "")
        content = str(f.get("content", "")).strip()
        if ftype in ("life_event", "preference", "relationship") and content and len(content) >= 2:
            facts.append({"type": ftype, "content": content})

    preferences = out.get("preferences") or {}
    if not isinstance(preferences, dict):
        preferences = {}

    result_dict = {"profile": profile, "facts": facts, "preferences": preferences}
    if profile or facts or preferences:
        logger.info(f"会话记忆提炼: profile={profile} facts={len(facts)} prefs={preferences}")
    else:
        logger.info("会话记忆提炼: 无值得记录的记忆")
    return result_dict
