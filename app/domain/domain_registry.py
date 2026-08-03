"""
领域包注册表——管理所有已加载的领域包，提供工具查询入口。

ToolMatcher 依赖 Registry 获取全量工具列表做向量检索。
Router 的校验闸门依赖 Registry 验证 tool_id 存在性。
"""

from app.models.domain import DomainPack, ToolSpec, Skill


class DomainRegistry:
    """领域包注册表——全局单例。

    职责：
    1. 注册/卸载领域包
    2. 提供全量工具扁平列表（ToolMatcher 用）
    3. 按 tool_id 查找工具（校验闸门用）
    """

    def __init__(self):
        self._domains: dict[str, DomainPack] = {}
        # 全量工具缓存：tool_id → ToolSpec
        self._tool_index: dict[str, ToolSpec] = {}
        # 向量检索后端会在 on_load 时由领域包自己注册
        # TODO: 集成向量存储（如 ChromaDB）

    async def register(self, domain: DomainPack) -> None:
        """注册一个领域包"""
        self._domains[domain.domain_id] = domain
        await domain.on_load()
        # 构建 tool_id 索引
        for tool in domain.get_all_tools():
            self._tool_index[tool.tool_id] = tool

    async def unregister(self, domain_id: str) -> None:
        """卸载一个领域包"""
        domain = self._domains.pop(domain_id, None)
        if domain is None:
            return
        await domain.on_unload()
        # 清除该领域包的 tool_id 索引
        for tool in domain.get_all_tools():
            self._tool_index.pop(tool.tool_id, None)

    def get_tool(self, tool_id: str) -> ToolSpec | None:
        """按 tool_id 查找工具（O(1)）"""
        return self._tool_index.get(tool_id)

    def get_all_tools(self) -> list[ToolSpec]:
        """获取所有已注册工具（扁平列表）"""
        return list(self._tool_index.values())

    def get_active_domain_ids(self) -> list[str]:
        """获取已激活的领域包 ID 列表"""
        return list(self._domains.keys())

    def is_tool_registered(self, tool_id: str) -> bool:
        """检查 tool_id 是否存在"""
        return tool_id in self._tool_index


# 全局单例
_registry: DomainRegistry | None = None


def get_registry() -> DomainRegistry:
    global _registry
    if _registry is None:
        _registry = DomainRegistry()
    return _registry
