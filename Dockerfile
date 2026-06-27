# ============================================================
# elephantRAG Docker Image
# ============================================================
# Build:  docker build -t elephant-rag .
# Run:    docker run -p 8000:8000 -p 8501:8501 \
#           -v $(pwd)/data:/app/data \
#           -v $(pwd)/.env:/app/.env:ro \
#           elephant-rag
# ============================================================

FROM python:3.11-slim

LABEL org.opencontainers.image.title="elephantRAG"
LABEL org.opencontainers.image.description="企业文档智能问答系统 — RAG (BM25+Dense) + Agent"
LABEL org.opencontainers.image.version="2.0"

# ── 替换为阿里云 Debian 镜像源（国内加速） ──────────
RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources \
 && sed -i 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources

# ── 系统依赖 ──────────────────────────────────────────
# - libgomp1:       PaddlePaddle OpenMP 运行时
# - libstdc++6:     C++ 标准库 (Paddle 共享库依赖)
# - libglib2.0:     PyMuPDF 运行时
# - curl:           健康检查
# - tini:           轻量 init，处理信号转发和僵尸进程
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libstdc++6 \
    libglib2.0-0 \
    libgl1 \
    libegl1\
    libgles2 \
    libxkbcommon0 \
    ca-certificates \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# ── 工作目录 ──────────────────────────────────────────
WORKDIR /app

# ── Python 依赖（分层缓存，阿里云 PyPI 镜像加速） ──────
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

# ── 预下载 PaddleOCR 模型（中英文混合） ──────────────────
# 避免容器首次调用 OCR 时的下载延迟 (~30s → 0s)
# PaddleOCR 3.x 首次调 OCR 会自动从 CDN 下载模型到 ~/.paddleocr
# 模型大小：约 100 MB (检测 + 识别 + 方向分类)
RUN python -c "\
import os, logging; \
logging.basicConfig(level=logging.WARNING); \
import numpy as np; \
from paddleocr import PaddleOCR; \
ocr = PaddleOCR(lang='ch', use_angle_cls=True); \
dummy = np.zeros((200, 200, 3), dtype=np.uint8); \
ocr.ocr(dummy); \
print('PaddleOCR models cached at', os.path.expanduser('~/.paddleocr')); \
"

# ── 项目文件 ──────────────────────────────────────────
COPY . .

# ── 权限 ──────────────────────────────────────────────
RUN mkdir -p /app/data /app/logs && chmod -R 755 /app

# ── 端口 ──────────────────────────────────────────────
EXPOSE 8000 8501

# ── 环境变量 ──────────────────────────────────────────
ENV API_BASE_URL=http://localhost:8000
ENV PYTHONUNBUFFERED=1

# ── 健康检查 ──────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# ── 启动 ──────────────────────────────────────────────
ENTRYPOINT ["tini", "--"]
CMD ["bash", "start.sh"]
