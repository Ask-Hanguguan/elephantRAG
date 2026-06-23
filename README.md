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

## 📁 文档上传

支持格式：`txt`、`pdf`、`csv`、`html`、`md`、`docx`、`xlsx`、`pptx`

上传方式：手动放入 `data/` 目录，运行入库脚本即可。

```bash
# 加载文档到知识库
python rag/vector_store.py
```

---

## 🗄️ 数据库

| 存储 | 说明 |
|------|------|
| **ChromaDB** | 向量数据库，存储文档的 embedding 向量 |
| **MD5Store** (SQLite) | 记录文件 MD5，增量更新时避免重复入库 |
| **BM25 稀疏索引** | 内存构建的关键词倒排索引 |

三级级联：文件变更时自动同步更新三处存储。

---

## ⚡ 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 将企业文档放入 data/ 目录

# 3. 加载文档到知识库
python rag/vector_store.py

# 4. (可选) 运行 benchmark 评估检索效果
python rag/benchmark.py

# 5. 启动 Web 界面
streamlit run app.py
```

---

## 🔑 环境变量

| 变量 | 说明 | 必填 |
|------|------|:----:|
| `DASHSCOPE_API_KEY` | 通义千问 API Key（模型和 Embedding 均通过此接口） | ✅ |

```bash
# Windows (CMD)
set DASHSCOPE_API_KEY=your-api-key-here

# Windows (PowerShell)
$env:DASHSCOPE_API_KEY="your-api-key-here"

# macOS / Linux
export DASHSCOPE_API_KEY="your-api-key-here"
```

## 📊 配置

- `config/chroma.yaml` — 向量库、分段、CCH、BM25 参数
- `config/rag.yaml` — 模型选择（embedding / chat）
- `config/benchmark.yaml` — 基准测试配置
