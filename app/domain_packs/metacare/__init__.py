"""
MetacarePack — 玄学领域包

注册的 Skill：
- tarot: 塔罗抽牌（tarot_draw）
- astrology: 星座占星（birth_chart / daily_transit / horoscope_daily）

设计原则：拿走这个包注入另一个领域包（如天气、股票），即成通用 agent——
路由/记忆/生成全部复用，只是领域能力换了一组。
"""

from app.models.domain import DomainPack, Skill
from app.domain_packs.metacare.tarot import TarotDrawTool
from app.domain_packs.metacare.astrology import (
    BirthChartTool,
    DailyTransitTool,
    HoroscopeDailyTool,
)


class MetacarePack(DomainPack):
    """玄学领域能力包。"""

    def __init__(self):
        super().__init__(
            domain_id="metacare",
            display_name="玄学陪伴",
            description="提供塔罗抽牌、本命星盘、流年星象、星座运势等玄学测算能力",
        )
        self._register_skills()

    def _register_skills(self) -> None:
        """注册所有 Skill 和 ToolSpec。"""

        # ── 塔罗 Skill ────────────────────────────
        tarot_skill = Skill(
            skill_id="tarot",
            display_name="塔罗牌",
            description="78 张经典塔罗牌占卜，支持单张快问快答和三张牌阵",
        )
        tarot_skill.add_tool(TarotDrawTool())
        self.add_skill(tarot_skill)

        # ── 星座 Skill ────────────────────────────
        astrology_skill = Skill(
            skill_id="astrology",
            display_name="星座占星",
            description="本命星盘生成、流年星象 Transit 计算、每日星座运势",
        )
        astrology_skill.add_tool(BirthChartTool())
        astrology_skill.add_tool(DailyTransitTool())
        astrology_skill.add_tool(HoroscopeDailyTool())
        self.add_skill(astrology_skill)


# ── 工厂函数 ────────────────────────────────────────────────

def create_metacare_pack() -> MetacarePack:
    """创建玄学领域包实例。框架用此函数扫描和加载。"""
    return MetacarePack()
