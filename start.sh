#!/bin/bash
# ============================================================
# elephantRAG - 启动脚本
# 启动 FastAPI(8000) + Streamlit(8501)
# ============================================================
set -e

# API base URL (same host, localhost)
export API_BASE_URL=http://localhost:8000

# 启动 FastAPI (后台)
echo "[start] Starting FastAPI (port 8000)..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# 等待 API 就绪
echo "[start] Waiting for API to be ready..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "[start] API is ready"
        break
    fi
    sleep 2
done

# 启动 Streamlit (前台)
echo "[start] Starting Streamlit (port 8501)..."
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --server.fileWatcherType none
