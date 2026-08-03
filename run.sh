#!/bin/bash
# Mysu 启动脚本：
#   1. 确保 Ollama 在运行（未运行则拉起，brew 优先，最多等 30s）
#   2. 检查默认模型已拉取（缺失则自动 pull）
#   3. 清除 Hermes 注入的 PYTHONPATH，保证 venv 隔离，启动 FastAPI
set -euo pipefail
cd "$(dirname "$0")"

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DEFAULT_MODEL="${DEFAULT_MODEL:-qwen2.5:3b}"

# ── 1. 确保 Ollama 在跑 ──────────────────────────────
if curl -s -m 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "[Mysu] Ollama 已在运行"
else
    echo "[Mysu] Ollama 未运行，正在启动..."
    if command -v brew >/dev/null 2>&1; then
        brew services start ollama
    else
        nohup ollama serve >/tmp/mysu-ollama.log 2>&1 &
    fi
    # 轮询等待就绪（最多 30 秒）
    for _ in $(seq 1 15); do
        if curl -s -m 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
            echo "[Mysu] Ollama 就绪"
            break
        fi
        sleep 2
    done
    if ! curl -s -m 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        echo "[Mysu] 错误：Ollama 启动失败，请手动检查（ollama serve / brew services info ollama）" >&2
        exit 1
    fi
fi

# ── 2. 检查默认模型已拉取 ────────────────────────────
if ! curl -s -m 5 "$OLLAMA_URL/api/tags" | grep -q "\"$DEFAULT_MODEL\""; then
    echo "[Mysu] 默认模型 $DEFAULT_MODEL 未拉取，正在下载（首次可能耗时较长）..."
    if ! ollama pull "$DEFAULT_MODEL"; then
        echo "[Mysu] 错误：模型 $DEFAULT_MODEL 拉取失败，请手动 ollama pull $DEFAULT_MODEL" >&2
        exit 1
    fi
fi

# ── 3. 启动 FastAPI ──────────────────────────────────
exec env -u PYTHONPATH .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8008 "$@"
