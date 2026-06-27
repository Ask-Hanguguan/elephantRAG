"""
FastAPI 应用入口
================================================
企业文档智能问答 REST API

启动方式:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

或通过 docker-compose 启动
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期:启动时初始化 KBManager"""
    logger.info("[API] 应用启动中...")
    from kb.manager import init_kb_manager
    init_kb_manager()
    logger.info("[API] 应用启动完成, API 服务就绪")
    yield
    logger.info("[API] 应用关闭")


app = FastAPI(
    title="ElephantRAG API",
    description="""
## ElephantRAG REST API

基于 RAG + ReAct Agent 的知识库智能检索问答服务。

### 功能
- **问答**: 基于 RAG 的智能问答（SSE 流式）
- **知识库管理**: 查看/切换知识库
- **文档管理**: 上传/列表/下载/删除/重向量化
- **会话管理**: 创建/列表/查看/删除对话
""",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health():
    return {"status": "ok", "service": "elephantrag-api"}


# ============================================================
# 注册路由
# ============================================================
from api.routes.chat import router as chat_router
from api.routes.knowledge import router as kb_router

app.include_router(chat_router)
app.include_router(kb_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
