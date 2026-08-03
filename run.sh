#!/bin/bash
# Mysu 启动脚本：清除 Hermes 注入的 PYTHONPATH，保证 venv 隔离
cd "$(dirname "$0")"
exec env -u PYTHONPATH .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8008 "$@"
