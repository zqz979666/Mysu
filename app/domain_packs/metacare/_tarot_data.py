"""
78 张经典塔罗牌的静态数据。

22 张大阿尔卡纳 (Major Arcana) + 56 张小阿尔卡纳 (Minor Arcana)
小阿尔卡纳分为四组：权杖(Wands)、圣杯(Cups)、宝剑(Swords)、星币(Pentacles)
每组 14 张：Ace-10 + 侍从(Page)、骑士(Knight)、王后(Queen)、国王(King)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TarotCard:
    """一张塔罗牌"""
    id: str                    # e.g. "major_00", "wands_01"
    name: str                  # 中文名
    name_en: str               # 英文名
    arcana: str                # "major" | "minor"
    suit: str                  # "trump" | "wands" | "cups" | "swords" | "pentacles"
    number: int                # 0-21 (major), 1-14 (minor: ace=1, page=11, knight=12, queen=13, king=14)
    keywords: list[str]        # 关键词
    meaning_upright: str       # 正位含义
    meaning_reversed: str      # 逆位含义


# ── Helper ──────────────────────────────────────────────────

def _card(
    id_: str, name: str, name_en: str, arcana: str, suit: str,
    number: int, keywords: list[str], up: str, rev: str,
) -> TarotCard:
    return TarotCard(
        id=id_, name=name, name_en=name_en,
        arcana=arcana, suit=suit, number=number,
        keywords=keywords, meaning_upright=up, meaning_reversed=rev,
    )


# ── Major Arcana (22 张) ───────────────────────────────────

MAJOR_ARCANA: list[TarotCard] = [
    _card("major_00", "愚者", "The Fool", "major", "trump", 0,
          ["开始", "天真", "冒险", "自由"],
          "新的开始、无限可能、跟随直觉的旅程。象征一颗自由无畏的心，建议你放下顾虑勇敢迈出第一步。",
          "冲动鲁莽、缺乏计划、不计后果。提醒你不要过于天真，需要更谨慎地评估风险。"),
    _card("major_01", "魔术师", "The Magician", "major", "trump", 1,
          ["创造", "能力", "意志", "资源"],
          "你拥有实现目标所需的一切资源和能力。意志力与行动力的完美结合，是展现才华的最佳时机。",
          "能力被浪费、欺骗、操纵。可能有人在利用你的信任，或者你自己的力量没有被善用。"),
    _card("major_02", "女祭司", "The High Priestess", "major", "trump", 2,
          ["直觉", "潜意识", "神秘", "内在智慧"],
          "倾听内心的声音，相信你的直觉。有些事情需要静待时机，答案隐藏在潜意识深处。",
          "忽视直觉、情绪封闭、秘密被隐藏。你可能在压抑自己的感受，或被某些不为人知的事困扰。"),
    _card("major_03", "女皇", "The Empress", "major", "trump", 3,
          ["丰饶", "滋养", "母性", "感官"],
          "丰盛与创造的季节，享受生活的美好。无论是在事业还是感情上，都是一个孕育和成长的时期。",
          "依赖过度、创造力枯竭、忽视自我。可能过于关注他人而忘了照顾自己，或沉溺于享乐。"),
    _card("major_04", "皇帝", "The Emperor", "major", "trump", 4,
          ["权威", "秩序", "掌控", "稳定"],
          "建立秩序和规则，用理性和权威掌控局面。是时候展现领导力，为混乱带来结构和纪律。",
          "专制、滥用权力、缺乏弹性。过于僵化会压制创造力，需要学会放手和信任他人。"),
    _card("major_05", "教皇", "The Hierophant", "major", "trump", 5,
          ["传统", "信仰", "教导", "仪式"],
          "遵循传统智慧，寻求导师的指引。适合学习、修行或接受正规的指导，回归内心的信仰。",
          "盲目服从、教条主义、反抗传统。你可能在质疑既有的规则，或感到被体制束缚。"),
    _card("major_06", "恋人", "The Lovers", "major", "trump", 6,
          ["爱情", "选择", "和谐", "价值观"],
          "重要的选择时刻，关乎内心真实的价值观。爱情、合作、和谐的关系正在形成，但需要真诚的抉择。",
          "错误的选择、不和谐、价值观冲突。可能面临两难困境，或关系中存在不真诚的因素。"),
    _card("major_07", "战车", "The Chariot", "major", "trump", 7,
          ["胜利", "意志力", "征服", "前进"],
          "凭借强大的意志力克服障碍，向着目标全力前进。这是一个需要果断行动和坚定信念的时刻。",
          "失控、失败、方向错误。你或许在强撑，内心中矛盾的力量正在交战，需要停下来重新审视。"),
    _card("major_08", "力量", "Strength", "major", "trump", 8,
          ["勇气", "耐心", "内在力量", "温柔"],
          "不是蛮力，而是以柔克刚的内在力量。用耐心和同理心驯服内心的野兽，真正的强大来自温柔。",
          "软弱、恐惧、失控。内在的不安正在影响你的判断，需要重新连接自己的力量源泉。"),
    _card("major_09", "隐士", "The Hermit", "major", "trump", 9,
          ["内省", "孤独", "寻求真理", "指引"],
          "暂时退隐，进入内心深处寻找答案。独处不是逃避，而是在寂静中点亮智慧之灯，照亮前路。",
          "过度孤立、逃避现实、恐惧孤独。你可能在用独处当借口，拒绝面对真实的问题。"),
    _card("major_10", "命运之轮", "Wheel of Fortune", "major", "trump", 10,
          ["命运", "转折", "循环", "机遇"],
          "命运的齿轮正在转动，新的循环即将开始。好运来临，顺势而为——变化本身就是唯一的恒常。",
          "厄运、失控、抗拒改变。你正在逆流而行，越是挣扎越感到无力，学会接受变化才能解脱。"),
    _card("major_11", "正义", "Justice", "major", "trump", 11,
          ["公平", "因果", "责任", "真相"],
          "种什么因得什么果，此刻需要做出公正的决断。真相将浮出水面，承担你应负的责任。",
          "不公、逃避责任、偏见。可能遭遇不公平对待，或你在某个决定中没有做到完全公正。"),
    _card("major_12", "倒吊人", "The Hanged Man", "major", "trump", 12,
          ["牺牲", "换个角度", "等待", "领悟"],
          "暂停行动，换个视角看世界。当下的停滞是为了更深的领悟，在等待中获得超越的智慧。",
          "无谓的牺牲、固执、停滞不前。你可能在为一个不值得的事坚持太久，该放手了。"),
    _card("major_13", "死神", "Death", "major", "trump", 13,
          ["结束", "转变", "重生", "放下"],
          "一个阶段彻底结束，为新生的到来清理空间。这不是终结而是蜕变——凤凰浴火才能重生。",
          "抗拒改变、停滞、恐惧结束。你在死死抓住已经不再属于你的东西，拒绝必要的告别。"),
    _card("major_14", "节制", "Temperance", "major", "trump", 14,
          ["平衡", "调和", "中庸", "耐心"],
          "寻找中道，在极端之间找到平衡点。融合对立的力量，用耐心和适度创造和谐的状态。",
          "失衡、放纵、缺乏节制。生活某方面已经偏离了平衡，需要重新审视和调整。"),
    _card("major_15", "恶魔", "The Devil", "major", "trump", 15,
          ["束缚", "欲望", "执念", "物质主义"],
          "你被某些欲望或执念所束缚——但锁链其实是松的。看清自己的阴影面，你随时可以选择挣脱。",
          "挣脱束缚、觉醒、看破幻象。你正在意识到自己的执念并开始摆脱它，光明即将到来。"),
    _card("major_16", "高塔", "The Tower", "major", "trump", 16,
          ["剧变", "崩塌", "震撼", "觉醒"],
          "突如其来的变故打破一切幻象。虽然痛苦，但这是必要的——只有摧毁虚假的根基，才能建起真实。",
          "抗拒变革、勉强维持、小幅动荡。你或许在强撑一个即将崩塌的结构，拖延只会让后果更严重。"),
    _card("major_17", "星星", "The Star", "major", "trump", 17,
          ["希望", "灵感", "治愈", "宁静"],
          "暴风雨后的宁静，内心充满希望和信念。宇宙在温柔地指引你，跟随灵感之光，治愈正在发生。",
          "失去信念、绝望、自我怀疑。你暂时看不到希望，但这只是阴云遮蔽了星光，不是星星消失了。"),
    _card("major_18", "月亮", "The Moon", "major", "trump", 18,
          ["幻象", "恐惧", "潜意识", "迷惑"],
          "前路笼罩迷雾，真假难辨。深入潜意识，正视内心的恐惧——月光虽然微弱，但足以引导你穿过黑夜。",
          "迷雾散去、恐惧被化解、真相浮现。你正在走出困惑，之前的不安开始变得清晰可辨。"),
    _card("major_19", "太阳", "The Sun", "major", "trump", 19,
          ["喜悦", "成功", "活力", "光明"],
          "最灿烂的祝福降临！一切变得明朗而温暖，成功、喜悦和生机充满你的世界。尽情享受这一刻。",
          "乌云遮日、短暂的阴霾、快乐受阻。只是暂时的阴影，太阳不会因此失去光芒——保持乐观。"),
    _card("major_20", "审判", "Judgement", "major", "trump", 20,
          ["觉醒", "召唤", "清算", "重生"],
          "内心的召唤正在响起——是时候审视过去、接受审判、然后迎来新生。这是一个灵魂层面的觉醒时刻。",
          "逃避召唤、自我怀疑、拒绝反思。你听到了内心的声音却在抗拒，拖延只会让不安加剧。"),
    _card("major_21", "世界", "The World", "major", "trump", 21,
          ["完成", "圆满", "整合", "成就"],
          "一个完整的周期圆满结束。你已完成了生命的某个重要篇章，感受到与宇宙的和谐统一。值得庆祝。",
          "未完成、欠缺收尾、接近成功但差一步。你离圆满只差临门一脚，不要在这个节点放弃。"),
]


# ── Minor Arcana (56 张) ───────────────────────────────────

_MINOR_SUITS = [
    ("wands", "权杖", ["热情", "事业", "行动", "创造"]),
    ("cups", "圣杯", ["情感", "关系", "直觉", "灵性"]),
    ("swords", "宝剑", ["思想", "冲突", "决断", "沟通"]),
    ("pentacles", "星币", ["物质", "财富", "健康", "务实"]),
]

_MINOR_RANKS = [
    (1, "ace", "首牌"),
    (2, "two", "二号"),
    (3, "three", "三号"),
    (4, "four", "四号"),
    (5, "five", "五号"),
    (6, "six", "六号"),
    (7, "seven", "七号"),
    (8, "eight", "八号"),
    (9, "nine", "九号"),
    (10, "ten", "十号"),
    (11, "page", "侍从"),
    (12, "knight", "骑士"),
    (13, "queen", "王后"),
    (14, "king", "国王"),
]

_COURT_NAMES = {11: "侍从", 12: "骑士", 13: "王后", 14: "国王"}

# 各花色的通用含义模板
_SUIT_THEMES = {
    "wands": {"domain": "事业与行动", "up": "新的开始、激情和创造力",
              "rev": "延误、缺乏动力或被压制"},
    "cups": {"domain": "情感与关系", "up": "情感的流动、直觉和灵性连接",
             "rev": "情绪波动、失落或情感上的抽离"},
    "swords": {"domain": "思想与冲突", "up": "清晰的思维、果断的行动和真理",
               "rev": "焦虑、内在冲突或伤人的言语"},
    "pentacles": {"domain": "物质与财富", "up": "务实的规划、稳定的增长和回报",
                  "rev": "物质的困扰、贪婪或财务上的不稳定"},
}

MINOR_ARCANA: list[TarotCard] = []

for suit_key, suit_cn, suit_kw in _MINOR_SUITS:
    theme = _SUIT_THEMES[suit_key]
    for num, rank_key, rank_cn in _MINOR_RANKS:
        card_id = f"{suit_key}_{rank_key}"
        if num <= 10:
            name = f"{suit_cn}{rank_cn}"
            name_en = f"{rank_cn.capitalize()} of {suit_cn}"
        else:
            court = _COURT_NAMES[num]
            name = f"{suit_cn}{court}"
            name_en = f"{court} of {suit_cn}"

        # 为每张牌生成简洁的含义
        if num == 1:  # Ace
            up = f"在{theme['domain']}领域，{theme['up']}的种子已经播下。这是一个充满潜力的起点。"
            rev = f"在{theme['domain']}领域，机会被错过或能量被浪费。{theme['rev']}的状态。"
        elif 2 <= num <= 5:
            up = f"在{theme['domain']}方面，{theme['up']}正在逐步展开。需要你主动把握。"
            rev = f"在{theme['domain']}方面出现一些波折。{theme['rev']}——需要停下来反思。"
        elif 6 <= num <= 10:
            up = f"在{theme['domain']}方面，{theme['up']}日趋成熟。成果正在显现，保持稳定。"
            rev = f"在{theme['domain']}方面遇到阻碍。{theme['rev']}。但不代表没有转机，只是需要调整策略。"
        elif num == 11:  # Page
            up = f"一位充满好奇和学习精神的年轻人，带来{theme['domain']}领域的新消息或新机会。保持开放的心态。"
            rev = f"在{theme['domain']}方面，消息延迟或计划不成熟。可能需要更多准备。"
        elif num == 12:  # Knight
            up = f"一位行动力十足的人物，正在{theme['domain']}领域快速推进。跟随这股冲劲，但别忘记耐心。"
            rev = f"在{theme['domain']}方面的行动过于急躁或冲动。减速比加速更明智。"
        elif num == 13:  # Queen
            up = f"一位成熟而富有同理心的形象，在{theme['domain']}领域展现温柔的力量。相信你的直觉。"
            rev = f"在{theme['domain']}方面，情绪可能影响了判断。过度的给予或索取都会造成失衡。"
        else:  # King
            up = f"一位权威和掌控力的象征，在{theme['domain']}领域展现成熟的领导力。用智慧驾驭局面。"
            rev = f"在{theme['domain']}方面，权力滥用或固执己见。真正的力量来自兼容并蓄。"

        card = _card(
            card_id, name, name_en, "minor", suit_key, num,
            suit_kw + [suit_cn], up, rev,
        )
        MINOR_ARCANA.append(card)

# ── 全量牌组 ───────────────────────────────────────────────

ALL_CARDS: list[TarotCard] = MAJOR_ARCANA + MINOR_ARCANA

# card_id → TarotCard 快速索引
CARDS_BY_ID: dict[str, TarotCard] = {c.id: c for c in ALL_CARDS}
