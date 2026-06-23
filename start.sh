#!/bin/bash
# ============================================================
# 启动脚本:同时运行 FastAPI 和 Streamlit
# ============================================================

# 初始化默认用户
echo "[start] 初始化默认用户..."
python -c "from auth.models import init_default_users; init_default_users()"

# 启动 FastAPI (后台)
echo "[start] 启动 FastAPI (端口 8000)..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 &

# 启动 Streamlit (前台)
echo "[start] 启动 Streamlit (端口 8501)..."
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
