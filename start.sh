#!/bin/bash
# ============================================================
# elephantRAG - 启动脚本
# Docker: tini (ENTRYPOINT) → 本脚本 → FastAPI + Streamlit
# ============================================================
set -euo pipefail

export API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

API_PID=""

cleanup() {
    echo "[start] Shutting down..."
    if [ -n "${API_PID}" ]; then
        kill "${API_PID}" 2>/dev/null || true
    fi
    echo "[start] Stopped"
    exit 0
}
trap cleanup SIGTERM SIGINT

# ── 1. 启动 FastAPI (后台) ────────────────────────────
echo "[start] Starting FastAPI on :8000"
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# ── 2. 等待健康检查 ────────────────────────────────────
echo "[start] Waiting for API..."
for i in $(seq 1 45); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "[start] API ready (pid=${API_PID})"
        break
    fi
    if ! kill -0 "${API_PID}" 2>/dev/null; then
        echo "[start] ERROR: FastAPI crashed on startup"
        exit 1
    fi
    sleep 2
done

# ── 3. 启动 Streamlit (前台) ────────────────────────────
echo "[start] Starting Streamlit on :8501"
streamlit run app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.fileWatcherType none \
    --browser.gatherUsageStats false &
ST_PID=$!

# ── 4. 持续运行，直到任一进程退出 ─────────────────────
# tini 收到 docker stop → SIGTERM → trap 触发 cleanup
# 任一子进程异常退出 → 立即退出容器
wait
