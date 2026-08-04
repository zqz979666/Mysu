"""
占星学完整数据模型。

包含：
- 12 星座（含太阳/月亮/上升的区分特质）
- 10 大行星（含天文轨道参数用于位置推算）
- 12 宫位（每个宫位管辖的人生领域）
- 5 大相位（合/六合/刑/三合/冲）及容许度
- 行星尊贵关系（守护/曜升/失势/落陷）
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


# ── 基本枚举 ────────────────────────────────────────────────

class Element(StrEnum):
    FIRE = "火"
    EARTH = "土"
    AIR = "风"
    WATER = "水"


class Modality(StrEnum):
    CARDINAL = "开创"
    FIXED = "固定"
    MUTABLE = "变动"


# ── 星座 ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ZodiacSign:
    """一个黄道星座的完整定义"""
    id: str                    # "aries", "taurus", ...
    name: str                  # 中文名
    symbol: str                # 符号 ♈♉♊♋♌♍♎♏♐♑♒♓
    date_range: str            # 日期范围
    element: Element
    modality: Modality
    ruler: str                 # 守护星
    # 太阳星座特质（外在性格、自我表达）
    sun_traits: list[str]
    sun_description: str
    # 月亮星座特质（内在情绪、安全感需求）
    moon_traits: list[str]
    moon_description: str
    # 上升星座特质（外在形象、第一印象）
    rising_traits: list[str]
    rising_description: str
    # 身体部位对应
    body_part: str


ZODIAC_SIGNS: dict[str, ZodiacSign] = {
    "aries": ZodiacSign(
        id="aries", name="白羊座", symbol="♈", date_range="3/21 - 4/19",
        element=Element.FIRE, modality=Modality.CARDINAL, ruler="mars",
        sun_traits=["勇敢", "直接", "竞争心强", "开拓精神"],
        sun_description="太阳白羊是黄道第一个星座，代表纯粹的自我、行动力和开创精神。你天生是先行者，凭直觉行动，讨厌拖泥带水。",
        moon_traits=["情绪直接", "需要独立空间", "易怒但转眼就忘", "热情冲动"],
        moon_description="月亮白羊需要即时满足情绪需求。愤怒来得快去得也快，内心永远住着一个长不大的孩子。",
        rising_traits=["第一印象果断", "气场直接", "行动派外表", "不掩饰情绪"],
        rising_description="上升白羊让人第一眼就觉得你充满能量和攻击性。你走路快、说话快、决策快，不爱拐弯抹角。",
        body_part="头部、面部",
    ),
    "taurus": ZodiacSign(
        id="taurus", name="金牛座", symbol="♉", date_range="4/20 - 5/20",
        element=Element.EARTH, modality=Modality.FIXED, ruler="venus",
        sun_traits=["踏实", "耐心", "享受生活", "固执"],
        sun_description="太阳金牛追求稳定和物质安全感。你重视感官享受，对美有天然的鉴赏力，一旦下定决心很难被动摇。",
        moon_traits=["需要安全感", "情绪稳定", "慢热但深情", "占有欲强"],
        moon_description="月亮金牛的情绪像大地一样稳固。你需要物质和情感的双重保障才能安心，不喜欢突如其来的变化。",
        rising_traits=["气质沉稳", "给人可靠感", "说话慢条斯理", "重视仪表"],
        rising_description="上升金牛给人第一印象是稳定和可靠。你不急于表达，但每一句话都有分量，气质沉稳如大地。",
        body_part="喉咙、颈部、甲状腺",
    ),
    "gemini": ZodiacSign(
        id="gemini", name="双子座", symbol="♊", date_range="5/21 - 6/21",
        element=Element.AIR, modality=Modality.MUTABLE, ruler="mercury",
        sun_traits=["好奇", "机智", "沟通能力强", "多变"],
        sun_description="太阳双子是信息的收集者和传播者。你的头脑永不停止运转，对世界充满好奇，擅长同时处理多项任务。",
        moon_traits=["情绪多变", "需要智性刺激", "善于用语言表达情感", "容易分心"],
        moon_description="月亮双子的情感世界丰富多彩但难以安定。你需要不断的新鲜感来滋养内心，否则会感到无聊和焦躁。",
        rising_traits=["健谈", "反应敏捷", "眼神灵动", "给人一种年轻感"],
        rising_description="上升双子给人第一印象是机智和健谈。你总是能迅速接上话题，让人感觉你充满活力、永远年轻。",
        body_part="手臂、肺部、神经系统",
    ),
    "cancer": ZodiacSign(
        id="cancer", name="巨蟹座", symbol="♋", date_range="6/22 - 7/22",
        element=Element.WATER, modality=Modality.CARDINAL, ruler="moon",
        sun_traits=["敏感", "顾家", "保护欲强", "念旧"],
        sun_description="太阳巨蟹的力量来自情感和归属感。家庭是你的堡垒，你擅长照顾他人，但也需要被温柔对待。",
        moon_traits=["情绪强烈", "念旧", "极度需要安全感", "直觉敏锐"],
        moon_description="月亮回到自己的守护星座，情绪力量极强。你的内心像潮汐一样有涨有落，对安全感的需求高于一切。",
        rising_traits=["温和", "有保护欲的外表", "情绪易读", "给人一种亲切感"],
        rising_description="上升巨蟹给人第一印象是有亲和力和保护欲。你像一层柔软的外壳，让人不自觉地想要靠近。",
        body_part="胸部、胃、消化系统",
    ),
    "leo": ZodiacSign(
        id="leo", name="狮子座", symbol="♌", date_range="7/23 - 8/22",
        element=Element.FIRE, modality=Modality.FIXED, ruler="sun",
        sun_traits=["自信", "慷慨", "创造力", "需要认可"],
        sun_description="太阳回到自己的守护星座，这是最耀眼的位置。你天生是舞台的中心，需要表达和被欣赏。",
        moon_traits=["需要被关注", "情感热烈", "骄傲", "忠诚"],
        moon_description="月亮狮子的情绪需要被看见和赞美。你内心渴望成为特别的人，在情感中慷慨而忠诚。",
        rising_traits=["气场强大", "自信", "有明星气质", "引人注目"],
        rising_description="上升狮子走进房间时自带光芒。你的存在感很强，第一印象就是自信和领导力。",
        body_part="心脏、脊椎、背部",
    ),
    "virgo": ZodiacSign(
        id="virgo", name="处女座", symbol="♍", date_range="8/23 - 9/22",
        element=Element.EARTH, modality=Modality.MUTABLE, ruler="mercury",
        sun_traits=["细致", "分析力强", "完美主义", "务实"],
        sun_description="太阳处女追求精确和完善。你有强大的分析能力，善于发现问题并解决，但也容易陷入过度批判。",
        moon_traits=["情绪内敛", "需要秩序感", "容易焦虑", "用行动表达关心"],
        moon_description="月亮处女的情绪需要条理和秩序来安抚。你通过照顾细节来表达爱，内心容易因不完美而焦虑。",
        rising_traits=["严谨", "谦逊", "看起来年轻", "注重细节"],
        rising_description="上升处女给人第一印象是整洁和谦逊。你不张扬但非常可靠，别人会注意到你对细节的掌控力。",
        body_part="消化系统、肠道",
    ),
    "libra": ZodiacSign(
        id="libra", name="天秤座", symbol="♎", date_range="9/23 - 10/23",
        element=Element.AIR, modality=Modality.CARDINAL, ruler="venus",
        sun_traits=["公正", "优雅", "社交能力强", "优柔寡断"],
        sun_description="太阳天秤追求平衡与和谐。你是天生的外交家，能看到事物的两面，但也因此容易陷入选择困难。",
        moon_traits=["需要和谐关系", "情绪由他人影响", "追求美感", "害怕冲突"],
        moon_description="月亮天秤的情绪高度依赖关系质量。你需要伴侣的陪伴来感到完整，害怕孤独和冲突。",
        rising_traits=["优雅", "社交魅力", "容貌端正", "给人好感"],
        rising_description="上升天秤天生带着金星的光环。你的外表和举止让人感到舒适和愉悦，社交场合如鱼得水。",
        body_part="肾脏、腰部",
    ),
    "scorpio": ZodiacSign(
        id="scorpio", name="天蝎座", symbol="♏", date_range="10/24 - 11/22",
        element=Element.WATER, modality=Modality.FIXED, ruler="pluto",
        sun_traits=["深邃", "执着", "洞察力强", "极端"],
        sun_description="太阳天蝎拥有强大的洞察力和转化能力。你善于看穿表象，追求深度的真相，不满足于肤浅。",
        moon_traits=["情感强烈", "占有欲", "直觉极致", "不轻易信任"],
        moon_description="月亮天蝎的情绪如深海暗流——表面平静、底层汹涌。你在情感中需要绝对的真实和忠诚。",
        rising_traits=["神秘", "眼神深邃", "不动声色", "有压迫感"],
        rising_description="上升天蝎给人第一印象是神秘且难以捉摸。你的眼神似乎能看透一切，让人既好奇又有些敬畏。",
        body_part="生殖系统、排泄系统",
    ),
    "sagittarius": ZodiacSign(
        id="sagittarius", name="射手座", symbol="♐", date_range="11/23 - 12/21",
        element=Element.FIRE, modality=Modality.MUTABLE, ruler="jupiter",
        sun_traits=["乐观", "自由", "爱冒险", "直率"],
        sun_description="太阳射手是黄道的探险家和哲学家。你追求自由和真理，乐观的天性让你永远能看到黑暗中的光亮。",
        moon_traits=["需要空间", "情绪大起大落", "乐观恢复快", "讨厌束缚"],
        moon_description="月亮射手的情绪需要自由的空间来呼吸。你的内心永远在寻找下一个冒险，不安于现状。",
        rising_traits=["开朗", "幽默", "不拘小节", "给人正面能量"],
        rising_description="上升射手让人第一眼就感受到你的乐观和幽默。你总是面带微笑，给人带来正面能量。",
        body_part="臀部、大腿、肝脏",
    ),
    "capricorn": ZodiacSign(
        id="capricorn", name="摩羯座", symbol="♑", date_range="12/22 - 1/19",
        element=Element.EARTH, modality=Modality.CARDINAL, ruler="saturn",
        sun_traits=["自律", "有野心", "务实", "责任感强"],
        sun_description="太阳摩羯是攀登者。你有清晰的目标和铁一般的自律，虽然起步可能慢，但每一步都踩得扎实。",
        moon_traits=["情绪克制", "需要成就感", "抑郁倾向", "用行动而非言语表达爱"],
        moon_description="月亮摩羯的情绪被土星的严肃包裹。你习惯压抑感受，通过承担责任和取得成就来获得情绪安全。",
        rising_traits=["严肃", "成熟", "少年老成", "有距离感"],
        rising_description="上升摩羯让人第一眼觉得你比实际年龄成熟。你不苟言笑，有一种天然的威严感。",
        body_part="膝盖、骨骼、牙齿、皮肤",
    ),
    "aquarius": ZodiacSign(
        id="aquarius", name="水瓶座", symbol="♒", date_range="1/20 - 2/18",
        element=Element.AIR, modality=Modality.FIXED, ruler="uranus",
        sun_traits=["独立", "创新", "博爱", "叛逆"],
        sun_description="太阳水瓶是黄道的革新者。你崇尚自由和平等，思维超前于时代，不喜欢被传统和规则束缚。",
        moon_traits=["情感抽离", "需要智性连接", "博爱不专一", "厌恶情绪绑架"],
        moon_description="月亮水瓶的情绪需要智性的理解和空间。你习惯用理性分析情感，害怕被情绪淹没。",
        rising_traits=["独特", "与众不同", "友好但疏离", "有未来感"],
        rising_description="上升水瓶让人第一眼觉得你与众不同。你有自己独特的气质，友好但不亲近，有一种若即若离的距离感。",
        body_part="小腿、脚踝、循环系统",
    ),
    "pisces": ZodiacSign(
        id="pisces", name="双鱼座", symbol="♓", date_range="2/19 - 3/20",
        element=Element.WATER, modality=Modality.MUTABLE, ruler="neptune",
        sun_traits=["浪漫", "慈悲", "想象力丰富", "易受影响"],
        sun_description="太阳双鱼是黄道的梦想家和疗愈者。你拥有丰富的想象力和同理心，边界感模糊但创造力无边。",
        moon_traits=["情绪极度敏感", "共情力强", "需要艺术滋养", "容易迷失"],
        moon_description="月亮双鱼的情绪像无边的大海。你能感受到他人的喜怒哀乐如同己出，需要艺术和灵性的滋养。",
        rising_traits=["梦幻", "温柔", "眼神迷离", "给人神秘感"],
        rising_description="上升双鱼给人第一印象是梦幻和温柔。你的眼神中似乎藏着另一个世界，让人想要保护你。",
        body_part="脚部、淋巴系统",
    ),
}


# ── 行星 ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Planet:
    """一颗占星行星的定义（含轨道参数用于位置计算）"""
    id: str
    name: str                   # 中文名
    symbol: str                 # 天文符号
    # 轨道参数（简化开普勒模型，用于位置近似推算）
    orbital_period_days: float  # 公转周期（天）
    # 占星含义
    governs: list[str]          # 掌管的人生领域
    keywords: list[str]         # 关键词


PLANETS: dict[str, Planet] = {
    "sun": Planet(
        id="sun", name="太阳", symbol="☉",
        orbital_period_days=365.25,
        governs=["自我认同", "人生目标", "外在表现", "父亲/权威"],
        keywords=["意志", "生命力", "创造力", "核心人格"],
    ),
    "moon": Planet(
        id="moon", name="月亮", symbol="☽",
        orbital_period_days=27.32,
        governs=["情绪", "潜意识", "家庭", "母亲/养育"],
        keywords=["情绪", "直觉", "记忆", "安全感"],
    ),
    "mercury": Planet(
        id="mercury", name="水星", symbol="☿",
        orbital_period_days=87.97,
        governs=["思维", "沟通", "学习", "短途旅行"],
        keywords=["逻辑", "表达", "信息处理", "商业"],
    ),
    "venus": Planet(
        id="venus", name="金星", symbol="♀",
        orbital_period_days=224.70,
        governs=["爱情", "审美", "价值观", "社交"],
        keywords=["魅力", "和谐", "享受", "吸引力"],
    ),
    "mars": Planet(
        id="mars", name="火星", symbol="♂",
        orbital_period_days=686.98,
        governs=["行动力", "欲望", "竞争", "冲突"],
        keywords=["勇气", "冲动", "性", "战斗力"],
    ),
    "jupiter": Planet(
        id="jupiter", name="木星", symbol="♃",
        orbital_period_days=4332.59,
        governs=["幸运", "扩张", "信仰", "高等教育"],
        keywords=["机遇", "成长", "乐观", "智慧"],
    ),
    "saturn": Planet(
        id="saturn", name="土星", symbol="♄",
        orbital_period_days=10759.22,
        governs=["责任", "限制", "纪律", "成熟"],
        keywords=["考验", "结构", "耐力", "业力"],
    ),
    "uranus": Planet(
        id="uranus", name="天王星", symbol="♅",
        orbital_period_days=30688.50,
        governs=["变革", "独立", "科技", "觉醒"],
        keywords=["突破", "意外", "创新", "自由"],
    ),
    "neptune": Planet(
        id="neptune", name="海王星", symbol="♆",
        orbital_period_days=60182.00,
        governs=["梦想", "直觉", "灵性", "幻象"],
        keywords=["灵感", "迷惑", "慈悲", "艺术"],
    ),
    "pluto": Planet(
        id="pluto", name="冥王星", symbol="♇",
        orbital_period_days=90560.00,
        governs=["转化", "权力", "深层心理", "死亡与重生"],
        keywords=["蜕变", "掌控", "执着", "毁灭与重建"],
    ),
}

# 快速移动行星（用于日运变化显著的）
FAST_PLANETS = ["sun", "moon", "mercury", "venus", "mars"]
# 慢速移动行星（用于长期运势）
SLOW_PLANETS = ["jupiter", "saturn", "uranus", "neptune", "pluto"]


# ── 12 宫位 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class House:
    """一个占星宫位"""
    number: int                # 1-12
    name: str                  # 中文名
    area: str                  # 管辖的人生领域
    keywords: list[str]
    description: str


HOUSES: dict[int, House] = {
    1: House(1, "命宫", "自我、外貌、气质、人生方向",
             ["自我", "人格", "外表", "第一印象"],
             "命宫代表你的外在人格、气质和给别人的第一印象。上升星座落入的宫位，是星盘中最个人化的部分。"),
    2: House(2, "财帛宫", "财富、价值观、物质资源",
             ["金钱", "价值观", "收入", "自我价值"],
             "财帛宫代表你对金钱和物质资源的态度。你的赚钱能力、消费习惯和自我价值感都在这里体现。"),
    3: House(3, "兄弟宫", "沟通、学习、短途旅行、兄弟姐妹",
             ["沟通", "学习", "兄弟姐妹", "短途旅行"],
             "兄弟宫代表你的沟通风格、早期教育和与身边人的互动方式。"),
    4: House(4, "田宅宫", "家庭、根源、房产、内在安全感",
             ["家庭", "父母", "根源", "安全感"],
             "田宅宫代表你的家庭背景、童年经历和内心深处的情感根基。天底(IC)落入的宫位。"),
    5: House(5, "子女宫", "创造力、恋爱、娱乐、子女",
             ["创意", "恋爱", "娱乐", "自我表达"],
             "子女宫代表你的创造力、浪漫和享乐方式。你在恋爱中的表现和对待孩子的方式都能在这里看到。"),
    6: House(6, "奴仆宫", "工作、健康、日常生活、服务",
             ["日常工作", "健康", "服务", "习惯"],
             "奴仆宫代表你的日常工作方式、健康和日常习惯。不是事业高度，而是每天的劳作节奏。"),
    7: House(7, "夫妻宫", "婚姻、合作、公开的敌人",
             ["婚姻", "合作", "伴侣", "一对一关系"],
             "夫妻宫代表你的婚姻和重要合作关系的模式。下降点(DSC)落入的宫位，是你投射到伴侣身上的特质。"),
    8: House(8, "疾厄宫", "深层转化、共有资源、性、死亡",
             ["转化", "投资", "遗产", "深层联结"],
             "疾厄宫代表生命中的深层转化——包括死亡与重生、共享资源和他人的钱。这是天蝎座的天然宫位。"),
    9: House(9, "迁移宫", "高等教育、哲学、长途旅行、信仰",
             ["高等教育", "旅行", "哲学", "信仰"],
             "迁移宫代表你对知识、远方的追求。高等教育、长途旅行和精神信仰都在这个宫位展开。"),
    10: House(10, "官禄宫", "事业、社会地位、公众形象、成就",
             ["事业", "成就", "名声", "社会地位"],
             "官禄宫代表你的人生事业和社会成就。天顶(MC)所在的宫位，是你在这个世界上的外在野心。"),
    11: House(11, "福德宫", "朋友、社群、理想、人道主义",
             ["朋友", "社群", "理想", "集体"],
             "福德宫代表你的社交圈和团体归属感。你如何交朋友、参与社群活动都在这个领域。"),
    12: House(12, "玄秘宫", "潜意识、业力、孤独、灵性",
             ["潜意识", "灵性", "业力", "隐退"],
             "玄秘宫是星盘中最神秘的部分，代表潜意识、前世业力、灵性修行和内在的自我消融。"),
}


# ── 相位 ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AspectType:
    """一种相位类型"""
    name: str                  # 中文名
    name_en: str               # 英文名
    angle: float               # 精确角度
    orb: float                 # 容许度（±度数）
    nature: str                # "和谐" | "挑战" | "中性"
    interpretation: str        # 通用的解读模板


ASPECT_TYPES: dict[str, AspectType] = {
    "conjunction": AspectType(
        name="合相", name_en="Conjunction", angle=0.0, orb=8.0,
        nature="中性",
        interpretation="两颗行星的能量融合在一起，彼此强化。这种相位的效果取决于两颗星的性质——吉星相合则双倍好运，凶星相合则挑战加倍。",
    ),
    "sextile": AspectType(
        name="六合", name_en="Sextile", angle=60.0, orb=6.0,
        nature="和谐",
        interpretation="两颗行星的能量互相支持，提供机会和顺畅的互动。这是温和的助力相位，需要主动把握才能发挥。",
    ),
    "square": AspectType(
        name="刑相", name_en="Square", angle=90.0, orb=7.0,
        nature="挑战",
        interpretation="两颗行星的能量产生紧张和摩擦。这种相位带来压力和挑战，但也是成长的催化剂——没有磨擦就没有进步。",
    ),
    "trine": AspectType(
        name="三合", name_en="Trine", angle=120.0, orb=8.0,
        nature="和谐",
        interpretation="两颗行星的能量顺畅流动，代表天赋和好运。这是最有利的相位，但也可能让人过于安逸而缺乏动力。",
    ),
    "opposition": AspectType(
        name="冲相", name_en="Opposition", angle=180.0, orb=8.0,
        nature="挑战",
        interpretation="两颗行星处于对立位置，需要在两者之间寻找平衡。冲相带来人际关系中的拉扯，但也是学会妥协和整合的机会。",
    ),
}


# ── 行星尊贵关系 ────────────────────────────────────────────

# 守护关系: planet → [ruled signs]
PLANET_RULERSHIP: dict[str, list[str]] = {
    "sun": ["leo"],
    "moon": ["cancer"],
    "mercury": ["gemini", "virgo"],
    "venus": ["taurus", "libra"],
    "mars": ["aries", "scorpio"],
    "jupiter": ["sagittarius", "pisces"],
    "saturn": ["capricorn", "aquarius"],
    "uranus": ["aquarius"],
    "neptune": ["pisces"],
    "pluto": ["scorpio"],
}

# 曜升关系: planet → [exaltation sign]
PLANET_EXALTATION: dict[str, str] = {
    "sun": "aries",
    "moon": "taurus",
    "mercury": "virgo",
    "venus": "pisces",
    "mars": "capricorn",
    "jupiter": "cancer",
    "saturn": "libra",
}

# 失势 = 守护星座的对宫
# 落陷 = 曜升星座的对宫

OPPOSITE_SIGN: dict[str, str] = {
    "aries": "libra", "taurus": "scorpio", "gemini": "sagittarius",
    "cancer": "capricorn", "leo": "aquarius", "virgo": "pisces",
    "libra": "aries", "scorpio": "taurus", "sagittarius": "gemini",
    "capricorn": "cancer", "aquarius": "leo", "pisces": "virgo",
}


def get_planet_dignity(planet_id: str, sign_id: str) -> str:
    """获取行星在某星座的尊贵状态"""
    if sign_id in PLANET_RULERSHIP.get(planet_id, []):
        return "入庙"  # Domicile — 最强
    if PLANET_EXALTATION.get(planet_id) == sign_id:
        return "曜升"  # Exaltation — 次强
    opposite = OPPOSITE_SIGN.get(sign_id, "")
    if opposite in PLANET_RULERSHIP.get(planet_id, []):
        return "失势"  # Detriment — 弱
    if PLANET_EXALTATION.get(planet_id) == opposite:
        return "落陷"  # Fall — 最弱
    return "中性"


# ── 星座别名映射 ────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    "白羊": "aries", "金牛": "taurus", "双子": "gemini", "巨蟹": "cancer",
    "狮子": "leo", "处女": "virgo", "天秤": "libra", "天蝎": "scorpio",
    "射手": "sagittarius", "摩羯": "capricorn", "水瓶": "aquarius", "双鱼": "pisces",
    "牧羊": "aries", "山羊": "capricorn",
}


def resolve_sign(name: str) -> str | None:
    """将任何形式的星座名解析为标准 sign_id"""
    name = name.strip().lower()
    if name in ZODIAC_SIGNS:
        return name
    for sid, info in ZODIAC_SIGNS.items():
        if info.name == name:
            return sid
    for alias, sid in _ALIASES.items():
        if alias in name:
            return sid
    return None


def all_sign_ids() -> list[str]:
    return list(ZODIAC_SIGNS.keys())
