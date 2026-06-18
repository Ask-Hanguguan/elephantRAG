# 📚 期末复习助手

大学生课程复习问答工具。上传课件资料（PDF、PPT、Word），即可对课程内容进行智能问答，快速复习备考。

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
【文档标题】：第8章 K-means聚类算法
【文档摘要】：K-means是一种基于距离的无监督学习算法...
【章节路径】：第8章 K-means聚类算法 > 8.2 算法流程
--- 
chunk 正文内容...
```

---

## 🤖 Agent 智能体

基于 LangChain ReAct 框架，大模型自主决定是否调用 RAG 检索工具：

1. 用户提问
2. Agent 判断是否需要查资料 → 调用 `rag_summarize`
3. 结合检索结果生成回答

> 去掉了天气查询、用户定位、报告生成等无关工具，只保留课程知识检索。

---

## 📁 文件上传

支持格式：`txt`、`pdf`、`csv`、`html`、`md`、`docx`、`xlsx`、`pptx`

上传方式：手动放入 `data/` 目录，运行入库脚本即可。

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
# 安装依赖
pip install -r requirements.txt

# 加载课件到知识库（将文件放入 data/ 后运行）
python rag/vector_store.py

# 运行 benchmark 评估检索效果
python rag/benchmark.py

# 启动 Web 界面
streamlit run app.py
```

---

## 📊 配置

- `config/chroma.yaml` — 向量库、分段、CCH、BM25 参数
- `config/rag.yaml` — 模型选择（embedding / chat）
- `config/benchmark.yaml` — 基准测试配置
