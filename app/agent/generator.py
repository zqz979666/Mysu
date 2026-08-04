"""
Generator——LLM 决策点②：汇总生成回复。

零决策——LLM 只做表达，不做规划。
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
    """回复生成器——LLM 决策点②。"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.last_tokens_in: int = 0
        self.last_tokens_out: int = 0

    async def generate(
        self,
        ctx: GeneratorContext,
        request_id: str = "",
        session_id: str = "",
    ) -> str:
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
                call_type="generator",
                request_id=request_id,
                session_id=session_id,
            )
        )

        self.last_tokens_in = result.tokens_in
        self.last_tokens_out = result.tokens_out

        return result.content
