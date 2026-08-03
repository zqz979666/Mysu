# Mysu

主打一个迷信。

## 架构

```
请求 → SessionManager → ContextLoader → Router(LLM①) → ValidationGate
     → ToolExecutor(并行) → ContextBuilder → Generator(LLM②) → 返回
     → 异步 Ingest
```

**整个 runtime 只有两个同步 LLM 调用点**（Router + Generator），所有复杂度在确定性的编排和校验上。

## 快速开始

```bash
./run.sh                # 一键启动（推荐）
```

或手动：

```bash
python3 -m venv .venv
env -u PYTHONPATH .venv/bin/pip install -r requirements.txt
env -u PYTHONPATH .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8008
```

> ⚠️ 本机（Hermes 环境）注入了 `PYTHONPATH` 指向其他 venv 的 site-packages，
> 会污染 Python 隔离。**所有 python/pip/uvicorn 操作必须带 `env -u PYTHONPATH`**，`run.sh` 已处理。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/chat` | 对话（7步流水线） |
| POST | `/api/events/pending` | 拉取推送事件 |

```bash
# 对话
curl -X POST http://127.0.0.1:8008/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "今天运势如何"}'
```

## 目录结构

```
app/
  main.py                  # FastAPI 入口
  models/                  # 数据模型（请求/响应/领域）
    requests.py            # ChatRequest, EventsPendingRequest
    responses.py           # ChatResponse, ErrorResponse
    domain.py              # DomainPack, Skill, ToolSpec, ExecutionContext
  agent/                   # 核心管道（纯函数流水线）
    agent_service.py       # 主编排器（7步流水线）
    session_manager.py     # 会话定位/分割/归档
    context_loader.py      # 四层记忆加载
    router.py              # LLM①：意图路由 + 工具选择 + 填参
    tool_matcher.py        # 确定性候选召回（非LLM）
    validation_gate.py     # tool_id/schema 校验
    tool_executor.py       # 并行执行 + 失败隔离
    context_builder.py     # 上下文组装 + token 预算
    generator.py           # LLM②：汇总生成回复
  llm/                     # LLM 客户端
    llm_client.py          # 统一调用/重试/token埋点
  memory/                  # 四层记忆系统
    memory_service.py      # Recall(同步)/Ingest(异步)
  knowledge/               # 知识检索
    knowledge_retriever.py # 元问题检索 + engine trace
  domain/                  # 领域包管理
    domain_registry.py     # 全局注册表
  domain_packs/            # 具体领域包
    metacare/              # 玄学领域包（待实现）
  observability/           # 可观测性
    logger.py              # 结构化日志
    metrics.py             # 指标埋点
requirements.txt
run.sh
```
