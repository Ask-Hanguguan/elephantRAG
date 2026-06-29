# 🐘 ElephantRAG

企业文档智能问答系统。上传企业内部文档（PDF、Word、Excel、PPT、Markdown、TXT、CSV、HTML），即可基于文档内容进行智能检索和问答。

---

## 🏗 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│  Streamlit Frontend (ui/)                                          │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────────┐ │
│  │  侧边栏       │  │  智能问答 Tab   │  │  知识库管理 Tab        │ │
│  │  KB 选择器    │  │  SSE 流式对话   │  │  上传/列表/删除/重向量化│ │
│  │  会话列表     │  │  消息历史       │  │  下载文档              │ │
│  └──────────────┘  └────────────────┘  └────────────────────────┘ │
│                        ↕  HTTP / SSE                                │
│              ApiClient (httpx, ui/api_client.py)                    │
└─────────────────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────── FastAPI Backend (api/) ───────────────────────┐
│  ┌────────────────┐  ┌───────────────┐  ┌────────────────────┐   │
│  │  chat 路由      │  │  knowledge 路由│  │  健康检查          │   │
│  │  SSE 流式对话   │  │  KB/文档 CRUD │  │  /api/health       │   │
│  │  会话持久化     │  │  同步/重建    │  │                     │   │
│  └───────┬────────┘  └──────┬────────┘  └────────────────────┘   │
└──────────┼──────────────────┼────────────────────────────────────┘
           ▼                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Core Logic (kb/)                                                    │
│  ┌──────────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │  KBManager        │  │  VectorStore   │  │  BM25SparseIndex     │ │
│  │  注册表管理       │  │  ChromaDB 封装  │  │  jieba 分词 + BM25   │ │
│  │  懒加载 KB 实例   │  │  文本切片       │  │  持久化 token 缓存   │ │
│  └───────┬──────────┘  └───────┬────────┘  └──────────┬───────────┘ │
│          │                    │                        │             │
│          ▼                    ▼                        ▼             │
│  ┌──────────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │  KBStore         │  │  FusionRetriever│ │  RagSummarizeService │ │
│  │  info.db (SQLite)│  │  RRF 融合排序   │ │  检索 + LLM 总结     │ │
│  └──────────────────┘  └────────────────┘  └──────────────────────┘ │
│                         ↑                                            │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  PDF Pipeline: PyMuPDF 文字提取 + PaddleOCR 图片 OCR        │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
         ↘ ↗
┌──────────────────────────────────────────────┐
│  Per-KB 物理隔离 (data/knowledge_base/{name}/) │
│  ├── info.db     文档元数据 + BM25 token 缓存 │
│  ├── content/    原始文档文件                   │
│  └── chroma_db/  ChromaDB 向量库               │
└──────────────────────────────────────────────┘
```

### 核心特性

- **前后端分离** — Streamlit 前端 ↔ FastAPI 后端，通过 HTTP/SSE 通信
- **知识库物理隔离** — 每个 KB 独立目录（info.db + chroma_db + content）
- **PDF 双路互补** — PyMuPDF 嵌入文字 + PaddleOCR 嵌入图片 OCR
- **融合检索** — BM25 关键词 + Dense 向量 → RRF 融合排序
- **Agent 智能问答** — ReAct Agent 自主判断是否需要检索文档
- **会话持久化** — SQLite 记录对话历史，支持会话切换/删除
- **多模型提供商** — DashScope / Ollama / OpenAI 独立配置 LLM 和 Embedding

---

## 🧠 RAG 检索流程

```
用户提问
   │
   ▼
ReAct Agent 判断是否需要检索
   │
   ▼
┌──────────────────────────────────┐
│  FusionRetriever                 │
│  ├─ Dense: ChromaDB 语义检索      │
│  ├─ BM25: jieba 分词 + 关键词检索 │
│  └─ RRF: 融合排序 → Top-K        │
└──────────────────────────────────┘
   │
   ▼
RagSummarizeService
   ├─ 格式化上下文
   └─ LLM 生成最终回答
```

### 支持三种检索策略

| 策略 | 方式 | 说明 |
|------|------|------|
| Dense Only | 稠密向量检索 | 纯语义相似度匹配 |
| BM25 Only | 稀疏检索 | 纯关键词匹配（jieba 分词） |
| **RRF Fusion** | BM25 + Dense → RRF | 默认策略，兼顾语义和关键词 |

RRF 评分公式：

```
score = 1/(k + rank_dense) + 1/(k + rank_bm25)
```

BM25 索引支持**持久化 token 缓存**，重启后可在数秒内恢复，无需重新 jieba 分词。

---

## 📄 PDF 处理管线

```
PDF 文件
  │
  ▼
PyMuPDF 逐页处理
  │
  ├─ page.get_text("text") ──→ 嵌入文字（<10ms/页，保留原始精度）
  │
  ├─ page.get_image_info(xrefs=True)
  │     │
  │     ├─ 宽高 < 页面 60% → 跳过（icon/logo）
  │     └─ 宽或高 ≥ 页面 60% → PaddleOCR 识别
  │           └─ 中英文混合 OCR，CPU 推理
  │
  └─ _normalize_text() 文本规范化 ──→ Document
       └─ NFKC 全半角转换 / 控制字符移除 / 空白合并
```

**优势**：
- 嵌入文字页不触发 OCR（速度 + 精度）
- 仅对嵌入图片 OCR（扫描件/图表内文字）
- Docker 镜像仅 **~1.2 GB**（对比 Docling + torch 方案的 3+ GB）

---

## 🤖 Agent 智能体

基于 LangChain ReAct Agent，大模型自主调用工具：

| 工具 | 说明 |
|------|------|
| `kb_retrieve` | 从当前知识库检索与问题相关的文档内容 |
| `kb_list_docs` | 列出当前知识库中的所有文档 |

Agent 只输出最终回答，中间推理和工具调用不展示给用户。

---

## 📁 文件结构

```
elephantRAG/
├── app.py                  # Streamlit 入口
├── agent/
│   ├── react_agent.py      # ReAct Agent
│   └── tools/
│       ├── agent_tools.py  # kb_retrieve / kb_list_docs
│       └── middleware.py   # 监控中间件
├── api/
│   ├── main.py             # FastAPI 应用
│   └── routes/
│       ├── chat.py         # SSE 流式对话 + 会话管理
│       └── knowledge.py    # 知识库/文档 CRUD
├── chat/
│   └── store.py            # 对话持久化 (ChatStore)
├── config/
│   ├── chroma.yaml         # 向量库 / 切片 / BM25 参数
│   ├── rag.yaml            # 模型提供商配置
│   └── prompts.yaml        # Prompt 模板路径
├── core/
│   ├── config.py           # YAML 配置加载
│   ├── logger.py           # 日志
│   └── path.py             # 路径解析
├── data/
│   ├── chat/               # 对话数据库
│   └── knowledge_base/     # 知识库（物理隔离）
│       └── {kb_name}/
│           ├── info.db     # 文档元数据 + BM25 token 缓存
│           ├── content/    # 原始文档
│           └── chroma_db/  # 向量库
├── kb/
│   ├── bm25_index.py       # BM25 稀疏索引（持久化缓存）
│   ├── fusion_retriever.py # RRF 融合检索
│   ├── loader.py           # 文档加载（PyMuPDF + PaddleOCR）
│   ├── manager.py          # KBManager 注册表 + 生命周期
│   ├── rag_service.py      # RAG 检索+总结
│   ├── store.py            # 每 KB 的 info.db (KBStore)
│   └── vector_store.py     # ChromaDB 封装
├── model/
│   ├── factory.py          # 模型工厂
│   └── provider.py         # DashScope / Ollama / OpenAI 提供商
├── prompts/
│   ├── rag_summarize.txt
│   ├── main_prompt.txt
│   └── report_prompt.txt
├── ui/
│   ├── api_client.py       # HTTP 客户端封装
│   ├── chat.py             # 智能问答页面
│   ├── knowledge.py        # 知识库管理页面
│   ├── session.py          # 会话状态初始化
│   ├── sidebar.py          # 侧边栏
│   └── styles.py           # 全局 CSS
├── Dockerfile
├── requirements.txt
└── start.sh                # Docker 启动脚本
```

---

## 🚀 快速开始

### 前置要求

- Python >= 3.11
- 通义千问 API Key（[DashScope 控制台](https://dashscope.console.aliyun.com/) 获取）
- Docker（可选，容器部署用）

### 一、本地启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 FastAPI 后端（端口 8000）
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 4. 在另一个终端启动 Streamlit 前端（端口 8501）
streamlit run app.py --server.port 8501
```

启动后访问 `http://localhost:8501` 进入 Web 界面。

### 二、Docker 部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY

# 2. 构建镜像
docker build -t elephant-rag .

# 3. 运行
docker run -d \
  --name elephant-rag \
  -p 8000:8000 \
  -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  elephant-rag
```

启动后访问：

| 服务 | 地址 | 说明 |
|------|------|------|
| Streamlit Web | http://localhost:8501 | 前端界面 |
| FastAPI API | http://localhost:8000/docs | Swagger 文档 |
| 健康检查 | http://localhost:8000/api/health | 健康检查 |

#### Windows (cmd)

```cmd
docker run -d --name elephant-rag -p 8000:8000 -p 8501:8501 -v %cd%\data:/app/data --env-file .env elephant-rag
```

---

## 🗄️ 存储架构

| 存储 | 说明 |
|------|------|
| **ChromaDB** (per KB) | `data/knowledge_base/{kb}/chroma_db/` — 文档 embedding 向量 |
| **KBStore** (per KB) | `data/knowledge_base/{kb}/info.db` — 文档元数据 + BM25 token 缓存 |
| **File Store** (per KB) | `data/knowledge_base/{kb}/content/` — 原始文档文件 |
| **ChatStore** (全局) | `data/chat/chat.db` — 会话和消息历史 |
| **Registry** (全局) | `data/knowledge_base/registry.json` — 知识库注册表 |

---

## 🌐 API 接口

| 端点 | 方法 | 说明 |
|------|:----:|------|
| `/api/health` | GET | 健康检查 |
| **知识库** | | |
| `/api/kb/list` | GET | 列出所有知识库 |
| `/api/kb/create` | POST | 创建知识库 |
| `/api/kb/switch` | POST | 切换当前知识库 |
| `/api/kb/{kb_name}/sync` | POST | 扫描 content/ 补登记遗漏文件 |
| `/api/kb/{kb_name}/rebuild-bm25` | POST | 重建 BM25 索引 |
| **文档** | | |
| `/api/kb/{kb_name}/upload` | POST | 上传文档 (multipart) |
| `/api/kb/{kb_name}/documents` | GET | 文档列表 |
| `/api/kb/{kb_name}/documents/{id}/download` | GET | 下载文档 |
| `/api/kb/{kb_name}/documents/{id}` | DELETE | 删除文档 |
| `/api/kb/{kb_name}/documents/{id}/revectorize` | POST | 重新向量化 |
| **对话** | | |
| `/api/chat/stream` | POST | SSE 流式对话 |
| `/api/chat/session/create` | POST | 创建会话 |
| `/api/chat/session/list` | GET | 会话列表 |
| `/api/chat/session/{id}/messages` | GET | 获取消息历史 |
| `/api/chat/session/{id}` | DELETE | 删除会话 |
| `/api/chat/session/{id}/title` | PUT | 更新标题 |

---

## 🔧 配置

### 模型提供商 (`config/rag.yaml`)

LLM 和 Embedding 可独立配置不同提供商：

```yaml
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

embedding:
  provider: dashscope
  dashscope:
    model_name: text-embedding-v3
  ollama:
    base_url: http://localhost:11434
    model_name: nomic-embed-text
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model_name: text-embedding-3-small
```

### 检索参数 (`config/chroma.yaml`)

```yaml
chunk_size: 200
chunk_overlap: 30
bm25:
  k1: 1.5
  b: 0.75
  epsilon: 0.25
fusion:
  final_top_k: 5
  rrf_k: 60
  dense_top_k: 10
  bm25_top_k: 10
```

### 环境变量 (`.env`)

| 变量 | 说明 | 必填 |
|------|------|:----:|
| `DASHSCOPE_API_KEY` | 通义千问 API Key | ✅ |
| `MODEL_PROVIDER` | 模型提供商 `dashscope` / `ollama` / `openai` | - |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `API_BASE_URL` | 后端地址 (Streamlit 用) | - |

---

## 🧪 维护操作

```bash
# 扫描 content/ 补登记遗漏文件
curl -X POST http://localhost:8000/api/kb/default/sync

# 强制重建 BM25 索引
curl -X POST http://localhost:8000/api/kb/default/rebuild-bm25

# 删除知识库（切换后再删）
# 当前无法删除正在使用的知识库
```

---

## 📦 Docker 镜像

- 基础镜像: `python:3.11-slim`
- 系统依赖: libgomp1, libstdc++6 (PaddlePaddle 运行时)
- OCR: PaddleOCR 3.x 检测 + 识别 + 方向分类模型预下载
- 启动: tini → start.sh → FastAPI + Streamlit
- 健康检查: 每 30s 检查 `/api/health`
- 镜像大小: **~1.2 GB**
