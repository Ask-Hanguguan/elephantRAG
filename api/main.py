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

from api.routes import auth, chat, documents
from auth.models import init_default_users
from utils.logger_handler import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期:启动时初始化"""
    logger.info("[api] 应用启动中...")
    # 初始化数据库和默认用户
    init_default_users()
    logger.info("[api] 应用启动完成,API 服务就绪")
    yield
    logger.info("[api] 应用关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="企业文档智能问答 API",
    description="""
## 企业文档智能问答 REST API

基于 RAG + ReAct Agent 的企业文档智能检索问答服务。

### 功能
- **认证**: JWT Token 登录/刷新
- **问答**: 基于 RAG 的智能问答(流式 SSE)
- **文档管理**: 上传/列表/删除企业文档

### 默认账户
- 用户名: admin
- 密码: admin123
""",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件(允许跨域,生产环境应限制 allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 健康检查
# ============================================================
@app.get("/api/v1/health", tags=["系统"], summary="健康检查")
def health():
    """健康检查接口"""
    return {"status": "ok", "service": "enterprise-qa-api"}


# ============================================================
# 注册路由
# ============================================================
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(documents.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
