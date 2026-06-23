# 📄 企业文档智能检索助手

企业文档智能问答工具。上传企业内部文档（制度规范、技术文档、项目文档、会议纪要等 PDF、PPT、Word），即可对文档内容进行智能检索和问答，快速获取所需信息。

---

## 🧠 RAG 检索流程

项目核心是基于多策略融合的 RAG 检索管线，流程如下：

```
用户提问 → 向量检索(Dense) + 关键词检索(BM25) → RRF 融合排序 → 段落合并 → LLM 总结回答
```

### 支持三种检索策略

| 策略 | 方式 | 说明 |
|------|------|------|
| **Dense Only** | 稠密向量检索 | 纯语义相似度匹配 |
| **BM25 Only** | 稀疏检索 | 纯关键词匹配 |
| **RRF Fusion** | BM25 + Dense → RRF | 默认融合策略，兼顾语义和关键词 |

### RRF 融合排序

采用倒数排序融合（Reciprocal Rank Fusion）将 BM25 和向量检索的结果合并重排：

```
score = 1/(k + rank_dense) + 1/(k + rank_bm25)
```

融合后取 Top-K，兼顾语义相关性和关键词命中。

### 段落合并 (Segment)

检索到的相邻 chunk 自动合并为完整段落，避免碎片化。合并时自动去重 CCH 头部信息，只保留第一段的标题和摘要。

### CCH 上下文增强

入库时自动为每个 chunk 注入文档标题、摘要和章节路径。
```
【文档标题】：项目需求规格说明书
【文档摘要】：本文档描述了XX系统的功能需求和非功能需求...
【章节路径】：项目需求规格说明书 > 3. 功能需求 > 3.1 用户管理
--- 
chunk 正文内容...
```

---

## 🤖 Agent 智能体

基于 LangChain ReAct 框架，大模型自主决定是否调用 RAG 检索工具：

1. 用户提问
2. Agent 判断是否需要查文档 → 调用 `rag_summarize`
3. 结合检索结果生成回答

---

---

## 📁 文档上传

支持格式：`txt`、`pdf`、`csv`、`html`、`md`、`docx`、`xlsx`、`pptx`

上传方式：

- **Streamlit Web 界面**：登录后在「文档管理」标签页上传
- **手动方式**：将文件放入 `data/` 目录，运行入库脚本

```bash
python rag/vector_store.py
```

---

## 🗄️ 数据库 / 存储

| 存储 | 说明 |
|------|------|
| **ChromaDB** | 向量数据库，存储文档的 embedding 向量 |
| **MD5Store** (SQLite) | 记录文件 MD5，增量更新时避免重复入库 |
| **BM25 稀疏索引** | 内存构建的关键词倒排索引 |
| **Users DB** (SQLite) | `data/users.db`，存储用户账户和密码哈希 |

三级级联：文件变更时自动同步更新三处存储。

---

## 🚀 快速开始

### 前置要求

- Python >= 3.11
- 通义千问 API Key（[DashScope 控制台](https://dashscope.console.aliyun.com/) 获取）

### 一、本地启动

```bash
# 1. 配置环境变量
cp .env.example .env
```

编辑 `.env` 文件，填入实际的 API Key 并生成一个随机 JWT_SECRET：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# 2. 安装依赖
pip install -r requirements.txt

# 3. 将企业文档放入 data/ 目录（或在 Web 界面中上传）
# 4. 加载文档到知识库
python rag/vector_store.py

# 5. 启动服务

# 方式 A：仅启动 Streamlit Web 界面（推荐首次使用）
streamlit run app.py

# 方式 B：同时启动 FastAPI REST API（端口 8000）+ Streamlit Web（端口 8501）
# 先在一个终端启动 API:
uvicorn api.main:app --host 0.0.0.0 --port 8000
# 再在另一个终端启动 Web:
streamlit run app.py --server.port 8501
```

启动后访问 `http://localhost:8501` 进入 Web 界面。

### 二、Docker 启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY 和 JWT_SECRET

# 2. 一键启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

启动后访问：

| 服务 | 地址 | 说明 |
|-----|------|------|
| Streamlit Web | http://localhost:8501 | 企业文档智能助手 Web 界面 |
| FastAPI API | http://localhost:8000/docs | REST API 文档（Swagger UI） |
| 健康检查 | http://localhost:8000/api/v1/health | API 健康检查 |

---

## 🔐 默认账户

首次启动自动创建管理员账户：

| 用户名 | 密码 | 角色 | 说明 |
|:-----:|:----:|:----:|------|
| `admin` | `admin123` | admin | 管理员，拥有所有权限 |

**生产环境请及时修改密码。**

### 角色权限

| 角色 | 文档上传 | 文档删除 | 问答 |
|:----:|:--------:|:--------:|:----:|
| admin | ✅ | ✅ | ✅ |
| editor | ✅ | ✅ | ✅ |
| viewer | ❌ | ❌ | ✅ |

---

## 🔑 环境变量

| 变量 | 说明 | 必填 | 默认值 |
|------|------|:----:|--------|
| `DASHSCOPE_API_KEY` | 通义千问 API Key | ✅ | - |
| `MODEL_PROVIDER` | 模型提供商 (`dashscope` / `ollama`) | - | `dashscope` |
| `JWT_SECRET` | JWT 签名密钥（生产环境必须修改） | ✅ | `enterprise-qa-secret-change-in-production` |
| `JWT_ALGORITHM` | JWT 签名算法 | - | `HS256` |
| `JWT_ACCESS_EXPIRE_MINUTES` | Access Token 过期时间（分钟） | - | `30` |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh Token 过期时间（天） | - | `7` |
| `DB_PATH` | 用户数据库路径 | - | `/app/data/users.db` |

### 设置方式

复制 `.env.example` 为 `.env` 并填入实际值：

```bash
cp .env.example .env
```

Docker 启动时自动加载 `.env` 文件。本地启动时需手动导出或使用 `python-dotenv`。

---

## 🤖 模型提供商切换

系统支持两种模型提供商，通过 `config/rag.yaml` 中的 `provider` 字段切换：

### DashScope（通义千问云 API，默认）

```yaml
provider: dashscope
chat_model_name: qwen3-max
embedding_model_name: text-embedding-v1
```

需设置环境变量 `DASHSCOPE_API_KEY`。

### Ollama（本地私有化部署）

```yaml
provider: ollama
ollama:
  base_url: http://localhost:11434
  chat_model_name: qwen2.5:7b
  embedding_model_name: nomic-embed-text
```

需本地运行 [Ollama](https://ollama.com/) 服务并下载相应模型。

---

## 🌐 REST API 文档

启动 FastAPI 后，访问以下地址查看交互式 API 文档：

| 文档 | 地址 |
|:----|:-----|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

### API 概览

| 端点 | 方法 | 说明 | 认证 |
|:----|:----:|------|:----:|
| `/api/v1/health` | GET | 健康检查 | ❌ |
| `/api/v1/auth/login` | POST | 用户登录，返回 JWT Token | ❌ |
| `/api/v1/auth/refresh` | POST | 刷新 Token | ✅ |
| `/api/v1/chat/query` | POST | 智能问答 | ✅ |
| `/api/v1/documents/upload` | POST | 上传文档 | ✅ (admin/editor) |
| `/api/v1/documents/list` | GET | 文档列表 | ✅ |
| `/api/v1/documents/delete` | DELETE | 删除文档 | ✅ (admin/editor) |

---

## 📊 配置

- `config/chroma.yaml` — 向量库、分段、CCH、BM25 参数
- `config/rag.yaml` — 模型选择（provider / embedding / chat）
- `config/agent.yaml` — ReAct Agent 参数（递归轮次、监控中间件等）

