"""
知识检索器——处理「元问题」（问测算原理、质疑结果等非测算类请求）。

被问"塔罗的原理是什么？""这个结果怎么出来的？"时，
Router 将意图判为 KNOWLEDGE 或 EXPLAIN，
Generator 在汇总回复前调用 KnowledgeRetriever 获取知识片段注入上下文。
"""

from dataclasses import dataclass, field


@dataclass
class KnowledgeHit:
    """一条知识检索命中"""

    doc_id: str
    content: str
    source: str  # "system_kb" | "domain_doc" | "engine_trace"
    score: float = 1.0


class KnowledgeRetriever:
    """知识检索。

    职责：
    1. 检索系统知识库（领域包自带的文档：塔罗原理、排盘规则）
    2. 读取 engine trace（上次测算的执行记录，回答"这结果怎么出来的？"）
    3. 按相关性排序返回 top-k 片段

    两个实现方向（TODO 阶段选一个）：
    a) 向量检索（ChromaDB / sqlite-vec）——适合长文档语义搜索
    b) BM25 关键词检索——适合 FAQ 型精确匹配
    """

    def __init__(self, top_k: int = 5):
        self.top_k = top_k
        # TODO: 对接向量存储或全文索引

    async def search(
        self,
        query: str,
        domain_ids: list[str] | None = None,
        include_trace: bool = False,
        session_id: str | None = None,
    ) -> list[KnowledgeHit]:
        """检索相关知识片段。

        Args:
            query: 用户问题
            domain_ids: 限定领域包，None 则全局搜索
            include_trace: 是否包含引擎 trace（EXPLAIN 意图用）
            session_id: 用于查找本会话的 engine trace

        Returns:
            按相关性排序的命中列表（最多 top_k 条）

        TODO: 对接实际检索后端。
        """
        # ── 占位实现 ──────────────────────────────
        return [
            KnowledgeHit(
                doc_id="placeholder",
                content=f"[知识库占位] 关于「{query}」的知识条目",
                source="system_kb",
            )
        ]

    async def get_trace(
        self, session_id: str, tool_call_index: int | None = None
    ) -> KnowledgeHit | None:
        """获取指定会话的引擎 trace。

        Args:
            session_id: 会话 ID
            tool_call_index: 指定第几次工具调用（None 则取最近一次）

        TODO: 对接 trace 存储。
        """
        return KnowledgeHit(
            doc_id=f"trace:{session_id}",
            content=f"[trace 占位] session={session_id} 的工具执行记录",
            source="engine_trace",
        )
