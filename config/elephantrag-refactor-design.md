# elephantRAG 重构设计文档

> 日期: 2026-06-27
> 状态: 已批准设计

---

## 1. 概述

对 elephantRAG 项目进行三个维度的重构：
1. **清理** — 删除客户认证功能（auth 模块、登录页面、JWT 依赖）
2. **知识库隔离** — 每个知识库物理独立，含自有文档存储、向量库、BM25 索引、元数据 SQLite
3. **目录重组** — 按功能模块(core/kb/model/api/ui)逐层组织

---

## 2. 删除认证

### 删除内容

| 文件 | 原因 |
|------|------|
| `auth/` 整个目录 | 不再需要用户认证系统 |
| `ui/login.py` | 登录页面 |
| `api/deps.py` | FastAPI JWT 认证依赖 |
| `auth` 路由引用 (`api/main.py`) | 移除 auth 路由注册 |

### 修改内容

| 文件 | 修改 |
|------|------|
| `app.py` | 移除登录判断，直接初始化 agent 并显示主界面 |
| `ui/session.py` | 移除 `user` 和 `access_token` 状态 |
| `ui/sidebar.py` | 移除用户信息展示和登出按钮，改为知识库选择器 |
| `ui/documents.py` → `ui/knowledge.py` | 移除角色权限判断，改为 KB 操作 |
| `ui/chat.py` | 移除用户相关引用 |
| `requirements.txt` | 移除 `python-jose`, `cryptography`, `passlib`, `bcrypt` |
| `api/main.py` | 移除 `init_default_users()` 调用和 auth 路由 |

---

## 3. 知识库系统

### 3.1 物理结构

每个知识库是一个独立目录，完全自包含：

```
data/knowledge_base/
├── registry.json              → KB 注册表(已有，保留格式)
├── default/                   → 默认知识库（启动时自动创建）
│   ├── info.db                → 文档元数据 SQLite（文档记录 + MD5）
│   ├── bm25.db                → BM25 分词缓存 SQLite
│   ├── content/               → 存放原始文档文件
│   └── chroma_db/             → ChromaDB 持久化（独立的向量存储实例）
├── demo/
│   ├── info.db
│   ├── bm25.db
│   ├── content/
│   └── chroma_db/
└── ...
```

### 3.2 info.db Schema（文档元数据）

```sql
CREATE TABLE documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name     TEXT NOT NULL,              -- 文件名
    file_path     TEXT NOT NULL,              -- 在 content/ 下的相对路径
    md5           TEXT NOT NULL,              -- 文件 MD5 十六进制字符串
    file_size     INTEGER,                    -- 文件大小(字节)
    file_type     TEXT,                       -- 扩展名(pdf/docx/txt...)
    status        TEXT DEFAULT 'uploaded',    -- uploaded | vectorized | error
    chunk_count   INTEGER DEFAULT 0,          -- 向量化后的 chunk 数量
    created_at    TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
```

### 3.3 bm25.db Schema（BM25 分词缓存）

```sql
-- BM25 分词缓存表（持久化分词结果，加速启动）
CREATE TABLE bm25_tokens (
    chunk_id      TEXT PRIMARY KEY,           -- ChromaDB chunk ID
    tokens        TEXT NOT NULL,              -- jieba 分词结果（空格分隔）
    doc_length    INTEGER NOT NULL,           -- token 数量
    doc_preview   TEXT,                       -- 原文前100字符（调试用）
    updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

-- BM25 索引元数据
CREATE TABLE bm25_meta (
    key           TEXT PRIMARY KEY,           -- avg_doc_length | total_docs | k1 | b | epsilon
    value         TEXT NOT NULL
);
```

### 3.3 文档状态流转

```
 上传 → status='uploaded' → 向量化 → status='vectorized'
                                     ↕ 重新向量化
                              status='vectorized' (更新向量)
                              ↓ 失败
                              status='error'
```

### 3.4 知识库操作

| 操作 | 行为 |
|------|------|
| **上传** | 1. 文件保存到 `content/` 2. 计算 MD5 3. 写入 `documents` 表(status=uploaded) 4. 可选自动向量化 |
| **向量化** | 1. 文档加载+切片 2. 写入 ChromaDB 3. 更新 `documents.status='vectorized'` + `chunk_count` 4. 更新 BM25 tokens |
| **删除** | 1. info.db 删除记录 2. ChromaDB 删除对应向量 3. 删除 `content/` 文件 4. 清理 BM25 tokens |
| **重新向量化** | 1. 从 info.db 取 md5 比对 2. 清除 ChromaDB 旧向量 3. 重新切片写入 4. 更新 BM25 tokens |

### 3.5 BM25 启动加速

```
启动时:
  bm25.db 有 bm25_tokens?
  ├─ 有 → 检查 tokens 总量 vs 已向量化文档的 chunk 总数
  │   ├─ 一致 → 从 tokens 直接构建 BM25Okapi（秒级，跳过 ChromaDB 读取和 jieba 分词）
  │   └─ 不一致 → 增量同步缺失 chunk
  └─ 无 → 从 ChromaDB 读取全量 → jieba 分词 → 写入 tokens 表 → 构建 BM25

文档变更时:
  - 新增向量化 → 对新增 chunk 分词 → 写入 bm25_tokens → 增量重建
  - 删除文档 → 删除对应 bm25_tokens → 重建
```

### 3.6 对话持久化 Schema

对话消息存储独立于知识库，使用全局 SQLite 数据库：

```sql
-- 会话表
CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,                -- UUID v4
    title         TEXT NOT NULL DEFAULT '新对话',  -- 会话标题（可自动生成或用户命名）
    kb_name       TEXT NOT NULL,                   -- 关联的知识库名称
    created_at    TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 消息表
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                  -- user | assistant | system | tool
    content         TEXT NOT NULL,                  -- Markdown 文本
    metadata        TEXT,                           -- JSON（工具调用日志、引用文档来源）
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_messages_conv ON messages(conversation_id, id);
```

**存储位置**：`data/chat/chat.db`

**设计要点**：
- 每个对话关联一个知识库（`kb_name`），切换知识库时创建新对话
- `metadata` 存储 JSON，记录 Agent 工具调用详情和引用的文档 chunk 来源
- `ON DELETE CASCADE` 确保删除会话时自动清理消息

---

## 4. 模型系统增强

### 4.1 目录结构

```
model/
├── __init__.py
├── factory.py        → 工厂函数(get_chat_model / get_embed_model)，对外接口不变
├── provider.py       → Provider 注册表 + 工厂逻辑
├── llm/
│   ├── base.py       → LLMProvider 抽象基类
│   ├── dashscope.py  → 通义千问 LLM
│   ├── ollama.py     → Ollama 本地 LLM
│   └── openai.py     → OpenAI 兼容 API 接口
└── embedding/
    ├── base.py       → EmbeddingProvider 抽象基类
    ├── dashscope.py  → DashScope text-embedding
    ├── ollama.py     → Ollama embeddings
    └── openai.py     → OpenAI 兼容嵌入接口
```

### 4.2 rag.yaml 配置结构（LLM/Embedding 独立配置）

```yaml
# ---- LLM 配置 ----
llm:
  provider: dashscope          # dashscope | ollama | openai
  dashscope:
    model_name: qwen-max
  ollama:
    base_url: http://localhost:11434
    model_name: qwen2.5:7b
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model_name: gpt-4o

# ---- Embedding 配置 ----
embedding:
  provider: dashscope          # dashscope | ollama | openai
  dashscope:
    model_name: text-embedding-async-v1
  ollama:
    base_url: http://localhost:11434
    model_name: nomic-embed-text
  openai:
    base_url: https://api.openai.com/v1
    model_name: text-embedding-3-small
```

### 4.3 Provider 注册表（provider.py）

```python
_PROVIDERS = {
    "llm": {
        "dashscope": DashScopeLLMProvider,
        "ollama": OllamaLLMProvider,
        "openai": OpenAILLMProvider,
    },
    "embedding": {
        "dashscope": DashScopeEmbeddingProvider,
        "ollama": OllamaEmbeddingProvider,
        "openai": OpenAIEmbeddingProvider,
    }
}
```

### 4.4 Agent 集成

RAG 对话不再直接调用 LLM，改为经由 ReactAgent 统一调度：

```
用户输入 → ReactAgent（LLM + Tools）→ 流式输出到前端
                    │
                    ├─ 工具: kb_retrieve    → 知识库检索（FusionRetriever）
                    ├─ 工具: kb_list_docs   → 列出当前知识库文档
                    └─ 工具: get_chat_history → 获取对话历史上下文
```

**Agent 流程**：
1. 用户发送消息 → 创建 `user` 消息 → 保存到 `messages` 表
2. ReactAgent 接收完整对话历史（含 system prompt 和当前 KB 上下文）
3. Agent 自主决定是否调用检索工具（知识库检索、文档列表查询）
4. 工具调用结果（chunk 文本、来源信息）追加到上下文
5. LLM 生成最终回答 → 流式 SSE 返回前端 → 保存 `assistant` 消息到 `messages` 表

**关键设计**：
- Agent 使用 `kb.manager.KBManager` 获取当前知识库的 VectorStoreService 和 BM25SparseIndex
- 工具调用日志（调用参数、检索到的 chunk 列表、相关性分数）写入 `messages.metadata`
- 保持 `agent/` 模块接口稳定，仅增加工具注册方式

### 4.5 对话持久化流程

```
┌──────────────────────────────────────────────────────┐
│  POST /api/chat/stream                               │
│  { content: "什么是 RAG?", kb_name: "default",       │
│    session_id: "uuid-xxx" }                          │
└─────────────┬────────────────────────────────────────┘
              │
              ▼
  1. ChatStore.save_message(session_id, role="user")
              │
              ▼
  2. ReactAgent.run(history, kb_context)
     ├─ 2a. 自动判断 → 是否需调用 kb_retrieve 工具
     ├─ 2b. 工具调用 → FusionRetriever 检索
     └─ 2c. LLM 生成回答
              │
              ▼
  3. SSE 流式推送给前端
     (data: { token: "..." })
     (data: { sources: [...] })
     (data: { done: true })
              │
              ▼
  4. ChatStore.save_message(session_id, role="assistant",
     content=full_response, metadata={sources, tool_calls})
```

**ChatStore 接口**：

| 方法 | 功能 |
|------|------|
| `create_session(kb_name, title?)` | 创建新会话，返回 session_id |
| `list_sessions()` | 列出所有会话（按 updated_at 降序） |
| `get_session(session_id)` | 获取会话信息 |
| `get_messages(session_id)` | 获取完整消息历史（用于 Agent 上下文构建） |
| `add_message(session_id, role, content, metadata?)` | 新增消息 |
| `delete_session(session_id)` | 删除会话及关联消息 |
| `update_title(session_id, title)` | 更新会话标题 |

### 4.6 chroma.yaml 配置变更

新增 Agent 和重向量化相关配置：

```yaml
# ---- Agent 配置 ----
agent:
  max_tool_rounds: 5                 # 单轮对话最大工具调用轮次
  system_prompt: prompts/rag_agent.txt  # Agent system prompt 模板
  enable_kb_retrieve: true           # 是否启用知识库检索工具
  enable_doc_list: false             # 是否启用文档列表工具

# ---- 重向量化 ----
re_vectorize:
  batch_size: 10                     # 批量重向量化文档数
  parallel: true                     # 是否并行处理
```

---

## 5. 完整目录结构

```
elephantRAG/
├── app.py                       → Streamlit 主入口（无认证，通过 FastAPI 通信）
├── core/                        → 基础设施层
│   ├── __init__.py
│   ├── config.py                → YAML 配置加载（从 utils/config_handler.py 合并）
│   ├── path.py                  → 路径解析（从 utils/path_tool.py 迁移）
│   └── logger.py                → 日志（从 utils/logger_handler.py 迁移）
├── chat/                        → 对话持久化模块（新增）
│   ├── __init__.py
│   └── store.py                 → ChatStore: 会话/消息 CRUD（SQLite）
├── kb/                          → 知识库核心模块
│   ├── __init__.py
│   ├── manager.py               → KBManager: 创建/列出/删除/选择知识库
│   ├── store.py                 → KBStore: info.db 操作（文档 CRUD、BM25 tokens）
│   ├── vector_store.py          → VectorStoreService: 每 KB 独立 ChromaDB 实例
│   ├── bm25_index.py            → BM25SparseIndex: 持久化加速，每 KB 独立
│   ├── fusion_retriever.py      → FusionRetriever: BM25 + Dense → RRF 融合
│   ├── loader.py                → 文档加载管线（PDF/Office→langchain Document+切片）
│   └── rag_service.py           → RagSummarizeService（重构后迁移至此）
├── model/                       → 模型工厂（增强，LLM/Embedding 独立）
│   ├── __init__.py
│   ├── factory.py               → 工厂函数
│   ├── provider.py              → Provider 注册表
│   ├── llm/                     → LLM 厂商实现
│   │   ├── base.py
│   │   ├── dashscope.py
│   │   ├── ollama.py
│   │   └── openai.py
│   └── embedding/               → Embedding 厂商实现
│       ├── base.py
│       ├── dashscope.py
│       ├── ollama.py
│       └── openai.py
├── agent/                       → Agent 模块（增强，工具注册 + 对话管理）
│   ├── __init__.py
│   ├── react_agent.py           → ReactAgent: LLM + 工具调度
│   └── tools/                   → Agent 工具集
│       ├── __init__.py
│       ├── agent_tools.py       → 检索/文档查询工具（从 KBManager 获取实例）
│       └── middleware.py        → 工具调用预处理/后处理
├── api/                         → FastAPI 后端（无 auth 依赖）
│   ├── __init__.py
│   ├── main.py                  → FastAPI app（注册所有路由）
│   └── routes/
│       ├── __init__.py
│       ├── chat.py              → 对话接口（SSE 流式 + 会话管理）
│       └── knowledge.py         → 知识库接口（上传/列表/下载/删除/向量化）
├── ui/                          → Streamlit 前端（通过 httpx/requests 调用 FastAPI）
│   ├── __init__.py
│   ├── api_client.py            → FastAPI HTTP 客户端封装（新增）
│   ├── session.py               → 会话状态（知识库选择、对话列表）
│   ├── chat.py                  → RAG 对话页面（SSE 流式展示 + 会话管理）
│   ├── knowledge.py             → 知识库管理页面（上传/列表/下载/删除/重向量化）
│   └── sidebar.py              → 侧边栏（知识库选择器、会话列表）
├── config/                      → YAML 配置文件
│   ├── chroma.yaml              → ChromaDB/BM25/融合检索/Agent 参数
│   ├── rag.yaml                 → 模型提供商配置（LLM+Embedding 独立）
│   ├── agent.yaml               → Agent 参数
│   └── prompts.yaml             → 提示词模板路径
├── data/
│   ├── chat/
│   │   └── chat.db              → 对话持久化 SQLite（新增）
│   └── knowledge_base/          → 知识库数据目录
│       ├── registry.json
│       └── default/
│           ├── info.db
│           ├── bm25.db
│           ├── content/
│           └── chroma_db/
├── prompts/                     → 提示词模板（保留现有文件）
├── requirements.txt             → 精简依赖（移除 auth 相关, 新增 httpx）
├── docker-compose.yml           → 保留
├── .env.example                 → 保留（更新注释）
└── README.md                    → 更新文档
```

---

## 6. API 接口层设计

UI（Streamlit）和后端（FastAPI）完全通过 HTTP 通信，不再直接调用 Python 模块。

### 6.1 接口清单

#### 对话接口（`api/routes/chat.py`）

| 方法 | 端点 | 功能 | 鉴权 |
|------|------|------|------|
| `POST` | `/api/chat/stream` | RAG 对话（SSE 流式） | 无 |
| `POST` | `/api/chat/session/create` | 创建新会话 | 无 |
| `GET` | `/api/chat/session/list` | 列出所有会话（降序） | 无 |
| `GET` | `/api/chat/session/{session_id}/messages` | 获取会话消息历史 | 无 |
| `DELETE` | `/api/chat/session/{session_id}` | 删除会话 | 无 |
| `PUT` | `/api/chat/session/{session_id}/title` | 更新会话标题 | 无 |

#### 知识库接口（`api/routes/knowledge.py`）

| 方法 | 端点 | 功能 | 鉴权 |
|------|------|------|------|
| `GET` | `/api/kb/list` | 列出知识库 | 无 |
| `POST` | `/api/kb/{kb_name}/upload` | 上传文档（multipart） | 无 |
| `GET` | `/api/kb/{kb_name}/documents` | 文档列表（含状态） | 无 |
| `GET` | `/api/kb/{kb_name}/documents/{doc_id}/download` | 下载文档 | 无 |
| `DELETE` | `/api/kb/{kb_name}/documents/{doc_id}` | 删除文档（含向量+BM25） | 无 |
| `POST` | `/api/kb/{kb_name}/documents/{doc_id}/revectorize` | 重新向量化 | 无 |

### 6.2 对话 SSE 协议

```
→ POST /api/chat/stream
   Request:  { content: "什么是 RAG?", kb_name: "default", session_id: "uuid-xxx" }

← SSE stream:
   event: token     data: {"token": "RAG 是..."}           # 逐 token 输出
   event: sources   data: {"sources": [{"file":"a.pdf",     # 引用来源
                                        "chunk_id":"...",
                                        "score":0.92}]}
   event: metadata  data: {"session_id": "uuid-xxx",        # 会话元信息
                           "tokens_used": 512}
   event: done      data: {"session_id": "uuid-xxx"}        # 结束标记
```

### 6.3 Streamlit UI 通信架构

Streamlit 前端通过 `ui/api_client.py` 封装 HTTP 调用：

```python
# ui/api_client.py —— FastAPI HTTP 客户端
class ApiClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120)

    async def chat_stream(self, content: str, kb_name: str, session_id: str | None):
        """RAG 对话（返回 SSE EventSource）"""
        ...

    async def upload_document(self, kb_name: str, file: BinaryIO):
        """上传文档（multipart/form-data）"""
        ...

    async def list_documents(self, kb_name: str) -> list[dict]:
        """获取文档列表"""
        ...

    async def download_document(self, kb_name: str, doc_id: int) -> bytes:
        """下载文档"""
        ...

    async def delete_document(self, kb_name: str, doc_id: int):
        """删除文档"""
        ...

    async def revectorize_document(self, kb_name: str, doc_id: int):
        """重新向量化"""
        ...
```

**通信链路**：
```
Streamlit 页面组件
    → ui/api_client.py (httpx)
        → HTTP/SSE → FastAPI Routes
            → KBManager / ChatStore / ReactAgent (业务逻辑)
```

**设计要点**：
- Streamlit 使用 `httpx.AsyncClient` 处理非阻塞 HTTP 和 SSE 流式响应
- 文档上传使用 multipart/form-data 编码
- SSE 流式输出在 Streamlit 中使用 `st.write_stream` 或手动迭代 `response.aiter_text()` 展示
- `base_url` 通过 Streamlit `secrets` 或环境变量配置

### 6.4 启动方式

```bash
# 方式一：分别启动（开发模式）
# Terminal 1: FastAPI 后端
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Streamlit 前端
streamlit run app.py --server.port 8501

# 方式二：单命令启动（生产模式）
# start.sh 同时启动 FastAPI 和 Streamlit
bash start.sh
```

---

### 6.5 缓存策略

避免前后端重复获取不变的数据，减少 API 调用和数据库查询。

#### 6.5.1 缓存层级

```
┌───────────────────────┐
│  Streamlit 会话缓存     │  → st.session_state（刷新页面后失效）
│  (内存级，最快)         │
├───────────────────────┤
│  ApiClient 内存缓存     │  → dict + TTL（页面内复用）
│  (内存级，次快)         │
├───────────────────────┤
│  FastAPI 服务端缓存     │  → cachetools.TTLCache（跨请求）
│  (进程内，通用)         │
└───────────────────────┘
```

#### 6.5.2 缓存策略表

| 数据类型 | 变更频率 | 策略 | TTL | 失效时机 |
|---------|---------|------|-----|---------|
| 知识库列表 | 极低（创建/删除） | ApiClient 内存缓存 + 手动刷新 | 300s | 创建/删除 KB 后立即失效 |
| 文档列表 | 低（上传/删除/重向量化） | Streamlit 会话缓存 | 页面生命周期 | 上传/删除/重向量化后手动刷新 |
| 会话列表 | 低（创建/删除） | Streamlit 会话缓存 | 页面生命周期 | 创建/删除会话后刷新 |
| 会话消息历史 | 低（仅对话时追加） | Streamlit 会话缓存 | 页面生命周期 | 发送新消息后追加，不刷新 |
| 配置信息 | 几乎不变 | FastAPI 服务端 `lru_cache` | 永久（进程内） | 重启服务 |

#### 6.5.3 ApiClient 内存缓存实现

```python
# ui/api_client.py — 带 TTL 的内存缓存
from time import time
from functools import wraps

def ttl_cache(ttl: int = 300):
    """带 TTL 的本地缓存装饰器"""
    def decorator(func):
        cache = {}
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # 生成缓存 key（忽略 self）
            key = str(args) + str(sorted(kwargs.items()))
            now = time()
            if key in cache and now - cache[key]["time"] < ttl:
                return cache[key]["data"]
            result = await func(self, *args, **kwargs)
            cache[key] = {"data": result, "time": now}
            return result
        wrapper.cache_clear = lambda: cache.clear()
        return wrapper
    return decorator

class ApiClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120)

    @ttl_cache(ttl=300)  # 5 分钟缓存
    async def list_knowledge_bases(self) -> list[dict]:
        resp = await self.client.get("/api/kb/list")
        resp.raise_for_status()
        return resp.json()

    async def upload_document(self, kb_name: str, file: BinaryIO):
        resp = await self.client.post(f"/api/kb/{kb_name}/upload", files={"file": file})
        resp.raise_for_status()
        self.list_knowledge_bases.cache_clear()  # 上传后刷新 KB 缓存（如有必要）
        return resp.json()
```

#### 6.5.4 Streamlit 会话缓存模式

```python
# ui/knowledge.py — Streamlit 会话缓存示例

@st.cache_data(ttl=600)  # Streamlit 内置缓存，跨 rerun 复用
def fetch_documents(kb_name: str) -> list[dict]:
    """获取文档列表（st.cache_data 会在输入不变时跳过执行）"""
    client = ApiClient()
    # st.cache_data 不支持异步，用同步 httpx 或 run_async
    import httpx
    resp = httpx.get(f"http://localhost:8000/api/kb/{kb_name}/documents")
    return resp.json()

# 上传后主动清除缓存
def on_upload_success(kb_name: str):
    st.cache_data.clear()  # 或精细清除: fetch_documents.clear(kb_name)
```

#### 6.5.5 FastAPI 服务端缓存

```python
# api/main.py — 服务端进程内缓存
from cachetools import TTLCache

# 全局缓存实例
server_cache = TTLCache(maxsize=100, ttl=300)

# 或在特定路由上使用
@router.get("/api/kb/list")
async def list_knowledge_bases():
    cache_key = "kb_list"
    if cache_key in server_cache:
        return server_cache[cache_key]
    result = await kb_manager.list_knowledge_bases()
    server_cache[cache_key] = result
    return result
```

#### 6.5.6 缓存注意事项

- **写操作后必须主动失效**：上传文档后清空文档列表缓存、创建/删除 KB 后清空 KB 列表缓存
- **Streamlit 的 `@st.cache_data` 在页面重加载时自动失效**，安全性较高
- **SSE 流式响应不缓存**，但消息已持久化到 SQLite，重新进入会话时从 DB 恢复
- **API 版本号**：如果接口升级，URL 路径用 `/api/v2/kb/list` 区分，避免缓存污染
- **跨进程场景**（多 worker）：考虑 Redis 替代进程内缓存，初期用进程内 TTLCache 即可

以下文件/目录将被**删除**：

| 路径 | 原因 |
|------|------|
| `auth/` | 整模块删除 |
| `ui/login.py` | 登录页面 |
| `api/deps.py` | JWT 认证依赖 |
| `rag/cch_preprocessor.py` | CCH 功能删除 |
| `rag/segment_extractor.py` | 相邻 chunk 合并功能删除 |
| `rag/md5_store.py` | MD5 管理并入 info.db |
| `utils/config_handler.py` | 合并到 core/config.py |
| `utils/path_tool.py` | 合并到 core/path.py |
| `utils/logger_handler.py` | 合并到 core/logger.py |
| `utils/file_handler.py` | 功能合并到 kb/loader.py |
| `utils/prompt_loader.py` | 合并到 core/config.py 或简化 |
| `rag/rag_service.py` | 重构为 `kb/rag_service.py`（RagSummarizeService 保留，移除 segment 依赖） |

---

## 8. 向后兼容

### Agent 模块接口说明

Agent 模块(`agent/`) 在本重构中**增强**，从简单 LLM 调用升级为完整工具调度：

- `agent/react_agent.py` → ReactAgent 集成，支持工具调用（知识库检索、文档列表等）
- `agent/tools/agent_tools.py` → 工具函数改为从 `KBManager` 获取当前活动知识库的 Service 实例
- 提供全局 `kb_manager` 单例，支持 `kb_manager.get_current_kb().vector_store` 模式
- `ChatStore` 负责对话持久化，Agent 在每次响应前后记录消息
- `app.py` 中 `ReactAgent` 的导入路径保持不变

### 数据迁移

1. **ChromaDB**: 现有 `data/chroma_db/` 全局目录 → 迁移到 `data/knowledge_base/default/chroma_db/`
2. **MD5.db**: 现位于 `data/chroma_db/MD5.db` → 合并迁移进 `data/knowledge_base/default/info.db` 的 `documents` 表
3. **已有 info.db**: `data/knowledge_base/<name>/info.db` 中如已有旧表 → 迁移到新 schema
4. **config/chroma.yaml**: 移除 `md5_hex_store`、`cch`、`segment` 等废弃配置项
5. **对话数据**: 旧对话记录不迁移，重构后使用 `data/chat/chat.db` 全新存储
   - 用户历史对话从旧存储（如有）导出为 JSON 自行导入

### 导入路径映射

| 旧路径 | 新路径 |
|--------|--------|
| `from utils.config_handler import chroma_conf` | `from core.config import chroma_conf` |
| `from utils.path_tool import get_abs_path` | `from core.path import get_abs_path` |
| `from utils.logger_handler import logger` | `from core.logger import logger` |
| `from rag.vector_store import VectorStoreService` | `from kb.vector_store import VectorStoreService` |
| `from rag.bm25_index import BM25SparseIndex` | `from kb.bm25_index import BM25SparseIndex` |
| `from rag.fusion_retriever import FusionRetriever` | `from kb.fusion_retriever import FusionRetriever` |
| `from rag.md5_store import MD5Store` | 删除，改用 `KBStore` |
| `from rag.cch_preprocessor import CCHPreprocessor` | 删除 |
| `from rag.segment_extractor import SegmentExtractor` | 删除 |
| `from rag.rag_service import RagSummarizeService` | `from kb.rag_service import RagSummarizeService` |
| `from model.factory import chat_model, embed_model` | 保留不变 |
| `from auth.* import ...` | 删除 |
| `from utils.file_handler import get_file_md5_hex, docling_loader` | `from kb.loader import get_file_md5_hex, docling_loader` |
| `from utils.prompt_loader import load_prompt` | `from core.config import load_prompt` |
| `from chat.store import ChatStore` | 新增模块，无旧路径 |
| `from agent.react_agent import ReactAgent` | 保留不变（增强） |

### 配置项变更

- `rag.yaml` 结构改为 LLM/Embedding 独立块（详见第4章）
- `chroma.yaml` 移除 `md5_hex_store`、`cch`、`segment` 配置
- `model.factory.chat_model` / `embed_model` 单例保留不变
- 模块级变量 `chroma_conf`、`rag_conf` 等 → `core.config.chroma_conf`、`core.config.rag_conf`
