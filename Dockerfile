# ============================================================
# 企业文档智能问答 - Dockerfile
# ============================================================
# 单容器同时运行 FastAPI(8000) 和 Streamlit(8501)
# 适合 MVP 阶段,ChromaDB 使用嵌入式模式

FROM python:3.11-slim

# 系统依赖(build-essential 编译用,libgl1/libglib2 docling 图像处理用)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件,利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/logs /app/chroma_db

# 暴露端口:8000=FastAPI, 8501=Streamlit
EXPOSE 8000 8501

# 启动脚本同时运行 API 和 Web
CMD ["sh", "start.sh"]
