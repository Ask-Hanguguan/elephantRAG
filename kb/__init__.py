"""
知识库核心模块

每个知识库(KB)物理独立，包含独立的:
- info.db: 文档元数据
- bm25.db: BM25 分词缓存
- content/: 原始文档文件
- chroma_db/: ChromaDB 向量持久化
"""
