"""
Generator——LLM 决策点②：汇总生成回复。

这是整个 runtime 两个同步 LLM 调用点中的第二个。
输入：用户消息 + 上下文 + 工具输出 + 知识片段
输出：自然语言回复

零决策——LLM 只做表达，不做规划。所有决策（意图/工具/参数）在 Router 就做完了。
"""

from app.llm.llm_client import LLMClient, LLMCallConfig
from app.agent.context_builder import GeneratorContext

GENERATOR_SYSTEM_PROMPT = """你是 Mysu，一位玄学陪伴助手。
你的回复基于以下信息：
- 用户画像和记忆（如果提供）
- 工具执行结果（如果提供）
- 相关知识（如果提供）

规则：
- 如果工具执行成功，基于工具输出给出自然友好的解读
- 如果工具执行失败，诚实告知并建议重试或换一种问法
- 如果是知识类问题，基于提供的知识片段回答，不编造
- 保持温暖、简洁、有共情力的语调
- 不要做新的功能性承诺（如"下次我帮你..."）"""


class Generator:
    """回复生成器——LLM 决策点②。

    面试话术：Router 做决策，Generator 做表达。
    两个调用点的职责边界泾渭分明——Router 决定「做什么」，
    Generator 决定「怎么说」。Generator 没有工具选择权，
    没有循环，它就是一个有上下文的翻译器。
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def generate(self, ctx: GeneratorContext) -> str:
        """生成自然语言回复。

        Args:
            ctx: ContextBuilder 组装完成的上下文

        Returns:
            自然语言回复文本

        TODO: 当前占位实现，对接 LLM 真实调用。
        """
        user_prompt = ctx.user_message
        if ctx.tool_outputs:
            user_prompt += f"\n\n{ctx.tool_outputs}"
        if ctx.knowledge_fragments:
            user_prompt += f"\n\n{ctx.knowledge_fragments}"

        result = await self.llm.call(
            LLMCallConfig(
                system_prompt=GENERATOR_SYSTEM_PROMPT
                + "\n\n" + ctx.system_prompt_fragment,
                user_prompt=user_prompt,
            )
        )

        return result.content
