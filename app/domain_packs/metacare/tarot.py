"""
塔罗 Skill：提供塔罗牌抽取与解读能力。

ToolSpec:
- tarot_draw: 从 78 张牌中随机抽取 1 或 3 张，返回牌面信息 + 解读
"""

import random
import time

from app.models.domain import ToolSpec, ToolResult, ExecutionContext
from app.domain_packs.metacare._tarot_data import ALL_CARDS, CARDS_BY_ID, TarotCard


# ── ToolSpec: tarot_draw ───────────────────────────────────

TAROT_DRAW_SCHEMA = {
    "type": "object",
    "properties": {
        "count": {
            "type": "integer",
            "enum": [1, 3],
            "description": "抽牌数量：1 张快问快答，3 张经典牌阵（过去-现在-未来）",
        },
        "question": {
            "type": "string",
            "description": "用户想问的问题（可选，用于解读上下文）",
        },
    },
    "required": ["count"],
}


class TarotDrawTool(ToolSpec):
    """随机抽取塔罗牌的纯函数工具。

    零 LLM 调用——纯 RNG。将来若需要"运势分析"则需要内部子 agent/子图，
    但抽牌本身永远是无状态的随机函数。
    """

    def __init__(self):
        super().__init__(
            tool_id="tarot_draw",
            display_name="塔罗抽牌",
            description="从 78 张塔罗牌中随机抽取指定数量的牌，返回牌面名称、正逆位和解读。支持抽 1 张（快问快答）或 3 张（过去-现在-未来牌阵）。",
            schema=TAROT_DRAW_SCHEMA,
        )

    async def execute(self, params: dict, ctx: ExecutionContext) -> ToolResult:
        count = params.get("count", 1)
        question = params.get("question", "")

        # 用当前时间微秒 + 用户 ID 作为随机种子（保证可复现）
        seed = int(time.time() * 1_000_000) + hash(ctx.session_id) % 1000000
        rng = random.Random(seed)

        # 随机抽牌
        drawn: list[tuple[TarotCard, bool]] = []  # (card, is_upright)
        pool = list(ALL_CARDS)
        rng.shuffle(pool)

        for i in range(min(count, len(pool))):
            card = pool[i]
            is_upright = rng.random() > 0.4  # 60% 正位, 40% 逆位
            drawn.append((card, is_upright))

        # 组装输出
        position_names: list[str]
        if count == 1:
            position_names = ["当前"]
        else:
            position_names = ["过去", "现在", "未来"]

        cards_output = []
        for i, (card, is_upright) in enumerate(drawn):
            orientation = "正位" if is_upright else "逆位"
            meaning = card.meaning_upright if is_upright else card.meaning_reversed

            cards_output.append({
                "position": position_names[i] if i < len(position_names) else f"第{i+1}张",
                "name": card.name,
                "name_en": card.name_en,
                "arcana": "大阿尔卡纳" if card.arcana == "major" else f"小阿尔卡纳·{card.suit}",
                "orientation": orientation,
                "keywords": card.keywords,
                "meaning": meaning,
            })

        # 生成 execution trace（用于元问题回答："这个结果怎么出来的？"）
        trace_lines = [
            f"执行: tarot_draw(count={count})",
            f"随机种子: {seed}",
            f"抽牌结果:",
        ]
        for c in cards_output:
            trace_lines.append(
                f"  [{c['position']}] {c['name']} ({c['orientation']})"
            )

        return ToolResult(
            tool_id=self.tool_id,
            success=True,
            output={
                "question": question,
                "count": count,
                "cards": cards_output,
            },
            trace="\n".join(trace_lines),
        )
