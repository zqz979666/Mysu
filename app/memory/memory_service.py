"""
记忆服务——四层记忆系统（SQLite 持久化）。

L0: 用户画像（出生日期/时间/地点/星座）
L1: 长期事实（偏好、生活事件）
L2: 玄学记录（历史塔罗/星盘结果）
L3: 短期状态（当前对话窗口）

Recall: 同步操作，Router 前加载上下文。
Ingest: 异步操作，回复返回后执行——包含自动画像提取。
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.storage.database import (
    db_execute,
    db_fetch_all,
    db_fetch_one,
    init_db,
    get_db_path,
)

logger = logging.getLogger("mysu.memory")


# ── 数据类 ──────────────────────────────────────────────────

@dataclass
class MemoryLayer:
    """单层记忆的检索结果"""
    layer: str  # "L0" | "L1" | "L2" | "L3"
    items: list[dict] = field(default_factory=list)


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    birth_date: str = ""         # YYYY-MM-DD
    birth_time: str = ""         # HH:MM
    birth_place: str = ""
    zodiac_sign: str = ""        # 太阳星座
    moon_sign: str = ""          # 月亮星座
    ascendant_sign: str = ""     # 上升星座
    gender: str = ""
    name: str = ""
    preferences: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "birth_date": self.birth_date,
            "birth_time": self.birth_time,
            "birth_place": self.birth_place,
            "zodiac_sign": self.zodiac_sign,
            "moon_sign": self.moon_sign,
            "ascendant_sign": self.ascendant_sign,
            "gender": self.gender,
            "name": self.name,
            "preferences": self.preferences,
        }

    @property
    def is_empty(self) -> bool:
        return not any([
            self.birth_date, self.birth_time, self.zodiac_sign,
            self.name, self.gender,
        ])

    def summary(self) -> str:
        """生成可注入 LLM prompt 的用户画像摘要"""
        parts = []
        if self.name:
            parts.append(f"昵称={self.name}")
        if self.birth_date:
            parts.append(f"出生日期={self.birth_date}")
        if self.birth_time:
            parts.append(f"出生时间={self.birth_time}")
        if self.zodiac_sign:
            parts.append(f"太阳星座={self.zodiac_sign}")
        if self.moon_sign:
            parts.append(f"月亮星座={self.moon_sign}")
        if self.ascendant_sign:
            parts.append(f"上升星座={self.ascendant_sign}")
        if self.gender:
            parts.append(f"性别={self.gender}")
        return ", ".join(parts) if parts else ""


# ── 正则提取 ────────────────────────────────────────────────

# 出生日期模式
_RE_BIRTH_DATE = re.compile(
    r"(\d{4})\s*[年/\-]\s*(\d{1,2})\s*[月/\-]\s*(\d{1,2})"
    r"|(\d{4})(\d{2})(\d{2})"
)
# 出生时间模式（支持 "下午2点半"、"上午8:00"、"14:30"）
_RE_BIRTH_TIME = re.compile(
    r"(?:下午|晚上|夜里|傍晚|PM|pm)\s*(\d{1,2})\s*[：:点]?\s*(半|\d{0,2})\s*(?:分)?"
    r"|(?:上午|早上|凌晨|早晨|AM|am)\s*(\d{1,2})\s*[：:点]?\s*(半|\d{0,2})\s*(?:分)?"
    r"|(\d{1,2})\s*[：:点]\s*(\d{1,2})\s*(?:分)?"
)

def _parse_birth_time(text: str) -> str | None:
    """从文本中解析出生时间，支持中文表达"""
    m = _RE_BIRTH_TIME.search(text)
    if not m:
        return None

    # 下午/晚上 → +12
    if m.group(1):
        hour = int(m.group(1))
        minute_str = m.group(2) or "0"
        minute = 30 if minute_str == "半" else int(minute_str)
        if hour != 12:  # 下午12点还是12点
            hour += 12
        return f"{hour:02d}:{minute:02d}"

    # 上午
    if m.group(3):
        hour = int(m.group(3))
        minute_str = m.group(4) or "0"
        minute = 30 if minute_str == "半" else int(minute_str)
        return f"{hour:02d}:{minute:02d}"

    # 纯数字格式 "14:30"
    if m.group(5):
        hour = int(m.group(5))
        minute = int(m.group(6))
        return f"{hour:02d}:{minute:02d}"

    return None
# 星座名模式（中文 + 英文）
_RE_ZODIAC = re.compile(
    r"(白羊|金牛|双子|巨蟹|狮子|处女|天秤|天蝎|射手|摩羯|水瓶|双鱼)"
    r"(?:座)?"
)

# 星座名 → ID 映射（用于存储）
_ZODIAC_NAME_TO_ID = {
    "白羊": "aries", "金牛": "taurus", "双子": "gemini",
    "巨蟹": "cancer", "狮子": "leo", "处女": "virgo",
    "天秤": "libra", "天蝎": "scorpio", "射手": "sagittarius",
    "摩羯": "capricorn", "水瓶": "aquarius", "双鱼": "pisces",
}


# 自指语言模式：只有匹配这些模式时才认为用户在说自己
_RE_SELF_REFERENCE = re.compile(
    r"我是.{0,12}(?:座|的|出生)"
    r"|我的.{0,12}(?:生日|星座|星盘|出生|运势|财运|爱情|事业|健康|学业|感情|工作)"
    r"|我生日|我出生于|我.{0,5}出生"
    r"|帮我算.{0,5}(?:星盘|运势|命盘)"
    r"|给我算.{0,5}(?:星盘|运势|命盘)"
)

# 强自指星座：星座名紧跟"我是"（仅允许"个"），最高置信的自述模式。
# 用于 LLM 未提取到时的双保险——只认这个模式，绝不覆盖"他是白羊座"。
_RE_STRONG_SELF_SIGN = re.compile(
    r"我是(?:个)?(白羊|金牛|双子|巨蟹|狮子|处女|天秤|天蝎|射手|摩羯|水瓶|双鱼)\s*座?"
)


def _extract_strong_self_sign(text: str) -> dict:
    """提取强自指星座（"我是XX座"）——regex 双保险专用，最严格。"""
    m = _RE_STRONG_SELF_SIGN.search(text)
    if not m:
        return {}
    sign_id = _ZODIAC_NAME_TO_ID.get(m.group(1))
    return {"zodiac_sign": sign_id} if sign_id else {}


def _has_self_reference(text: str) -> bool:
    """判断文本是否在描述用户自己的信息（而非打听他人）。

    仅用于 LLM 不可用时的 regex 兜底，不参与 LLM 判断路径。
    """
    return bool(_RE_SELF_REFERENCE.search(text))


def _extract_profile_hints(text: str) -> dict:
    """从文本中提取用户画像线索（纯正则，零 LLM）。

    仅作为 LLM 不可用时的兜底。LLM 可用时画像提取由 LLM 全权判断。
    只提取自指性信息——用户明确在说自己时才保存。
    例如：
      "我是白羊座"       → 提取 zodiac_sign=aries
      "我的生日是1995年"  → 提取 birth_date
      "看看白羊座运势"    → 不提取（打听他人信息）
      "帮我算算星盘"       → 不提取（没有具体数据，只是请求）

    Returns:
        提取到的字段 dict（只包含非空字段）
    """
    # 安全检查：用户是否在说自己的信息？
    if not _has_self_reference(text):
        return {}

    hints: dict = {}

    # 出生日期
    m = _RE_BIRTH_DATE.search(text)
    if m:
        if m.group(1):  # YYYY-MM-DD 格式
            y, mo, d = m.group(1), m.group(2), m.group(3)
            hints["birth_date"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        else:  # YYYYMMDD
            hints["birth_date"] = f"{m.group(4)}-{m.group(5).zfill(2)}-{m.group(6).zfill(2)}"

    # 出生时间
    birth_time = _parse_birth_time(text)
    if birth_time:
        hints["birth_time"] = birth_time

    # 星座
    m = _RE_ZODIAC.search(text)
    if m:
        sign_cn = m.group(1)
        sign_id = _ZODIAC_NAME_TO_ID.get(sign_cn)
        if sign_id:
            hints["zodiac_sign"] = sign_id

    return hints


# ── MemoryService ───────────────────────────────────────────

class MemoryService:
    """四层记忆系统（SQLite 持久化）。"""

    def __init__(self, db_path: str = "data/mysu.db", llm_client=None):
        self.db_path = db_path
        self.llm = llm_client  # 可选：用于 LLM 画像提取
        # 延迟初始化 extractor，避免循环导入
        self._extractor = None
        init_db(db_path)

    # ── Recall（同步）──────────────────────────────

    async def recall(
        self, session_id: str, user_id: str
    ) -> list[MemoryLayer]:
        """同步查询四层记忆。

        Returns:
            按 L0→L3 排序的记忆层列表
        """
        layers: list[MemoryLayer] = []

        # L0: 用户画像
        profile = await self.get_profile(user_id)
        layers.append(MemoryLayer(
            layer="L0",
            items=[profile.to_dict()] if not profile.is_empty else [],
        ))

        # L1: 长期事实
        facts = await self.get_facts(user_id, limit=10)
        layers.append(MemoryLayer(
            layer="L1",
            items=[{"content": f["content"], "type": f["fact_type"]}
                   for f in facts],
        ))

        # L2: 近期玄学记录
        readings = await self.get_recent_readings(user_id, limit=5)
        layers.append(MemoryLayer(
            layer="L2",
            items=[{"tool_id": r["tool_id"], "query": r["query"] or "",
                    "date": r["created_at"]}
                   for r in readings],
        ))

        # L3: 短期状态（当前会话最近 10 轮）
        state = await self.get_session_state(session_id, limit=10)
        layers.append(MemoryLayer(
            layer="L3",
            items=[{"role": s["role"], "content": s["content"][:200]}
                   for s in state],
        ))

        return layers

    async def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像"""
        row = await db_fetch_one(
            "SELECT * FROM user_profiles WHERE user_id=?",
            (user_id,),
        )
        if row is None:
            return UserProfile(user_id=user_id)

        prefs = {}
        if row["preferences"]:
            try:
                prefs = json.loads(row["preferences"])
            except json.JSONDecodeError:
                pass

        return UserProfile(
            user_id=user_id,
            birth_date=row["birth_date"] or "",
            birth_time=row["birth_time"] or "",
            birth_place=row["birth_place"] or "",
            zodiac_sign=row["zodiac_sign"] or "",
            moon_sign=row["moon_sign"] or "",
            ascendant_sign=row["ascendant_sign"] or "",
            gender=row["gender"] or "",
            name=row["name"] or "",
            preferences=prefs,
        )

    async def get_facts(self, user_id: str, limit: int = 10) -> list[dict]:
        """获取长期事实"""
        rows = await db_fetch_all(
            "SELECT fact_type, content FROM long_term_facts "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in rows]

    async def get_recent_readings(
        self, user_id: str, limit: int = 5
    ) -> list[dict]:
        """获取近期玄学记录"""
        rows = await db_fetch_all(
            "SELECT tool_id, query, result_json, created_at FROM readings "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in rows]

    async def get_session_state(
        self, session_id: str, limit: int = 10
    ) -> list[dict]:
        """获取当前会话状态"""
        rows = await db_fetch_all(
            "SELECT role, content FROM session_state "
            "WHERE session_id=? ORDER BY turn_index DESC, id DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed([dict(r) for r in rows]))

    # ── Ingest（异步）──────────────────────────────

    async def ingest(
        self, session_id: str, user_id: str, turn: dict
    ) -> None:
        """异步入库一回合对话。

        Args:
            turn: {
                "user_message": "...",
                "assistant_reply": "...",
                "intent": "execute",
                "tool_results": [{"tool_id": "...", "success": True}, ...],
                "expect_fields": ["birth_date", ...],  # 可选：澄清上下文
            }
        """
        user_msg = turn.get("user_message", "")
        assistant_reply = turn.get("assistant_reply", "")
        intent = turn.get("intent", "")
        tool_results = turn.get("tool_results", [])

        # ── 1. 登记/更新用户画像（即时提取，仅强自指）──
        # 只信"我是/我的"；替他人询问（"他是我朋友，白羊座"）绝不落库。
        # 澄清回答的归属判断由 session 级提炼（extract_session_memory）负责。
        await self._ensure_profile(user_id)

        hints = await self._extract_profile_llm(user_msg)
        if hints:
            await self._update_profile_from_hints(user_id, hints)
            logger.info(
                f"记忆 Ingest: LLM 提取画像 user={user_id} hints={hints}"
            )

        # ── 2. 保存 L3 会话状态 ───────────────────
        # 获取当前轮次
        max_turn_row = await db_fetch_one(
            "SELECT COALESCE(MAX(turn_index), 0) as max_turn "
            "FROM session_state WHERE session_id=?",
            (session_id,),
        )
        turn_index = (max_turn_row["max_turn"] if max_turn_row else 0) + 1

        # 用户消息
        await db_execute(
            "INSERT INTO session_state (session_id, user_id, turn_index, role, content, metadata_json) "
            "VALUES (?, ?, ?, 'user', ?, ?)",
            (session_id, user_id, turn_index, user_msg,
             json.dumps({"intent": intent}, ensure_ascii=False)),
        )
        # 助手回复
        await db_execute(
            "INSERT INTO session_state (session_id, user_id, turn_index, role, content, metadata_json) "
            "VALUES (?, ?, ?, 'assistant', ?, ?)",
            (session_id, user_id, turn_index, assistant_reply,
             json.dumps({"intent": intent}, ensure_ascii=False)),
        )

        # ── 3. 保存 L2 玄学记录 ───────────────────
        for tr in tool_results:
            if tr.get("success"):
                await db_execute(
                    "INSERT INTO readings (session_id, user_id, tool_id, query) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, user_id, tr.get("tool_id", ""), user_msg),
                )

        logger.info(
            f"记忆 Ingest 完成: user={user_id} session={session_id} "
            f"turn={turn_index} intent={intent} "
            f"tools={[t.get('tool_id') for t in tool_results]}"
        )

    async def _ensure_profile(self, user_id: str) -> None:
        """确保用户画像记录存在"""
        existing = await db_fetch_one(
            "SELECT user_id FROM user_profiles WHERE user_id=?",
            (user_id,),
        )
        if existing is None:
            await db_execute(
                "INSERT INTO user_profiles (user_id) VALUES (?)",
                (user_id,),
            )

    async def _update_profile_from_hints(
        self, user_id: str, hints: dict
    ) -> None:
        """将提取到的画像线索更新到数据库"""
        # 只更新非空字段
        fields = []
        params = []
        for key, value in hints.items():
            if value:
                fields.append(f"{key}=?")
                params.append(value)

        if not fields:
            return

        fields.append("updated_at=datetime('now')")
        params.append(user_id)

        await db_execute(
            f"UPDATE user_profiles SET {', '.join(fields)} WHERE user_id=?",
            tuple(params),
        )

    # ── 管理 ───────────────────────────────────────

    async def update_profile(
        self, user_id: str, profile: dict
    ) -> None:
        """手动更新用户画像"""
        await self._ensure_profile(user_id)
        fields = []
        params = []
        for key in ["birth_date", "birth_time", "birth_place",
                     "zodiac_sign", "moon_sign", "ascendant_sign",
                     "gender", "name"]:
            if key in profile:
                fields.append(f"{key}=?")
                params.append(profile[key])
        if "preferences" in profile:
            fields.append("preferences=?")
            params.append(json.dumps(profile["preferences"], ensure_ascii=False))

        if fields:
            fields.append("updated_at=datetime('now')")
            params.append(user_id)
            await db_execute(
                f"UPDATE user_profiles SET {', '.join(fields)} WHERE user_id=?",
                tuple(params),
            )

    async def add_fact(
        self, user_id: str, fact_type: str, content: str,
        session_id: str = "", confidence: float = 1.0,
    ) -> None:
        """添加一条长期事实"""
        await db_execute(
            "INSERT INTO long_term_facts (user_id, fact_type, content, "
            "source_session_id, confidence) VALUES (?, ?, ?, ?, ?)",
            (user_id, fact_type, content, session_id, confidence),
        )

    async def archive_session(self, session_id: str) -> None:
        """归档会话（清理 L3，保留 L2）"""
        pass

    # ── LLM 画像提取 ──────────────────────────────

    async def _extract_profile_llm(
        self,
        user_msg: str,
    ) -> dict:
        """用 LLM 提取用户画像（如果可用），回退到 regex。

        核心原则：不做规则预判（自指检测/关键词过滤）——LLM 全权判断
        用户是否在自述、提取哪些字段。仅强自指（"我是/我的"）会被提取；
        替他人转述的信息由会话级提炼负责（见 extract_session_memory）。
        """
        # 尝试 LLM（无任何规则预判）
        if self.llm is not None:
            try:
                if self._extractor is None:
                    from app.memory.profile_extractor import ProfileExtractor
                    self._extractor = ProfileExtractor(self.llm)
                llm_hints = await self._extractor.extract(user_msg)
            except Exception:
                llm_hints = {}
            # LLM 提取成功 → 直接采用
            if llm_hints:
                return llm_hints
            # LLM 未提取到（3B 小模型抽风/理解偏差）→ 强自指双保险。
            # 只认"我是XX座"这种最高置信模式（regex 兜底太粗，会把
            # "帮我算下我朋友的运势，他是白羊座"误判成自指，污染画像）。
            regex_hints = _extract_strong_self_sign(user_msg)
            if regex_hints:
                logger.info(
                    f"画像提取: LLM 未提取到，regex 强自指兜底命中 {regex_hints}"
                )
                return regex_hints
            return {}

        # 无 LLM：纯 regex 兜底
        return _extract_profile_hints(user_msg)

    # ── 待澄清状态 ────────────────────────────────

    async def set_pending_clarification(
        self, session_id: str, user_id: str,
        tool_id: str, missing: list[str], ask_message: str,
    ) -> None:
        """记录一个待澄清的请求（用户缺参数，等待回答）。"""
        await db_execute(
            """INSERT INTO pending_clarifications
               (session_id, user_id, tool_id, missing_params, ask_message)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 tool_id=excluded.tool_id,
                 missing_params=excluded.missing_params,
                 ask_message=excluded.ask_message,
                 created_at=datetime('now')""",
            (session_id, user_id, tool_id,
             json.dumps(missing, ensure_ascii=False), ask_message),
            context="clarification",
        )
        logger.info(
            f"澄清挂起: session={session_id} tool={tool_id} "
            f"missing={missing}"
        )

    async def update_pending_clarification(
        self, session_id: str,
        missing: list[str], partial: dict, ask_message: str,
    ) -> None:
        """多轮澄清：更新仍缺的字段 + 累积已收集的参数。"""
        await db_execute(
            """UPDATE pending_clarifications SET
                 missing_params=?, partial_params=?, ask_message=?
               WHERE session_id=?""",
            (json.dumps(missing, ensure_ascii=False),
             json.dumps(partial, ensure_ascii=False),
             ask_message, session_id),
            context="clarification",
        )
        logger.info(
            f"澄清累积: session={session_id} missing={missing} "
            f"partial={partial}"
        )

    async def get_pending_clarification(
        self, session_id: str
    ) -> dict | None:
        """查询会话是否有待澄清状态。"""
        row = await db_fetch_one(
            "SELECT * FROM pending_clarifications WHERE session_id=?",
            (session_id,), context="clarification",
        )
        if row is None:
            return None
        result = dict(row)
        result["missing_params"] = json.loads(result["missing_params"])
        result["partial_params"] = json.loads(
            result.get("partial_params") or "{}"
        )
        return result

    async def clear_pending_clarification(self, session_id: str) -> None:
        """清除待澄清状态（用户回答后）。"""
        await db_execute(
            "DELETE FROM pending_clarifications WHERE session_id=?",
            (session_id,), context="clarification",
        )

    # ── 会话级记忆提炼（session 结束后全量判断）──────────────
    # USER-DIRECTED：即时提取只信强自指；替他人询问（"帮我朋友算，他
    # 是白羊座"）的归属判断、长期事实、偏好，统一由本方法在 session
    # 结束后用全量对话上下文交给 LLM 判断。这是画像落库的权威入口之一。

    async def extract_session_memory(
        self, session_id: str, user_id: str
    ) -> bool:
        """提炼一个已结束会话的长期记忆。

        读该会话全量对话 → LLM 判断（画像字段 + 长期事实 + 偏好）→ 落库。
        幂等：每个 session 只提炼一次（memory_extractions 标记）。

        Returns:
            True=提炼并落库了至少一类记忆；False=无内容/已提炼/无 LLM
        """
        # 幂等：已提炼过则跳过
        done = await db_fetch_one(
            "SELECT 1 FROM memory_extractions WHERE session_id=?",
            (session_id,), context="memory_extract",
        )
        if done:
            return False

        # 读该会话全量对话（按轮次正序）
        rows = await db_fetch_all(
            "SELECT role, content FROM session_state "
            "WHERE session_id=? ORDER BY turn_index ASC, id ASC",
            (session_id,), context="memory_extract",
        )
        if not rows:
            return False

        transcript = "\n".join(
            f"[{'用户' if r['role'] == 'user' else '助手'}] {r['content']}"
            for r in rows
        )
        # 超长会话截断保护（保留最近部分）
        if len(transcript) > 8000:
            transcript = "…(前文省略)…\n" + transcript[-8000:]

        if self.llm is None:
            return False

        from app.memory.profile_extractor import extract_session_memory as _extract
        memory = await _extract(self.llm, transcript)

        profile = memory.get("profile") or {}
        if profile:
            await self._ensure_profile(user_id)
            await self._update_profile_from_hints(user_id, profile)
            logger.info(
                f"会话级提炼画像: user={user_id} session={session_id} "
                f"hints={profile}"
            )

        for f in memory.get("facts") or []:
            await self.add_fact(
                user_id, f.get("type", "life_event"), f.get("content", ""),
                session_id=session_id,
            )
        if facts := memory.get("facts"):
            logger.info(
                f"会话级提炼事实: user={user_id} session={session_id} "
                f"facts={facts}"
            )

        prefs = memory.get("preferences") or {}
        if prefs:
            await self.update_profile(user_id, {"preferences": prefs})
            logger.info(
                f"会话级提炼偏好: user={user_id} session={session_id} "
                f"prefs={prefs}"
            )

        # 标记已提炼（无论是否有内容，避免反复空转）
        await db_execute(
            "INSERT INTO memory_extractions (session_id, user_id) "
            "VALUES (?, ?) ON CONFLICT(session_id) DO NOTHING",
            (session_id, user_id), context="memory_extract",
        )
        return bool(profile or memory.get("facts") or prefs)
