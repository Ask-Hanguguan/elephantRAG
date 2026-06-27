"""
每个知识库独立的向量存储 — ChromaDB 封装

与 KBStore 配合，每 KB 拥有独立的 ChromaDB 持久化目录。
"""

import os
from typing import Optional, Callable

from core.config import chroma_conf
from core.logger import logger
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from model.factory import embed_model


class VectorStoreService:
    def __init__(self, kb_path: str, kb_store=None, collection_name: str = "kb_docs"):
        persist_dir = os.path.join(kb_path, "chroma_db")
        os.makedirs(persist_dir, exist_ok=True)

        self.kb_store = kb_store

        self.vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embed_model,
            persist_directory=persist_dir,
        )

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf.get("chunk_size", 200),
            chunk_overlap=chroma_conf.get("chunk_overlap", 30),
            separators=chroma_conf.get("separators", ["\n\n", "\n", ".", "!", "?", " ", ""]),
            length_function=len,
        )

        self._bm25_index = None

    def process_and_store(self, file_path: str, md5_hex: str) -> tuple[bool, int]:
        """
        处理单个文件：加载 → 切片 → 写入 ChromaDB
        返回 (成功与否, chunk数量)
        """
        from kb.loader import load_document

        documents = load_document(file_path)
        if not documents:
            logger.warning(f"[VectorStore] {file_path} 无有效文本内容")
            return False, 0

        split_docs = self.splitter.split_documents(documents)
        if not split_docs:
            logger.warning(f"[VectorStore] {file_path} 切片后无内容")
            return False, 0

        # 注入元数据
        for i, chunk in enumerate(split_docs):
            chunk.metadata["source"] = file_path
            chunk.metadata["file_md5"] = md5_hex
            chunk.metadata["chunk_index"] = i

        # 清除旧向量 (同 source 路径)
        try:
            self.vector_store._collection.delete(where={"source": {"$eq": file_path}})
        except Exception as e:
            logger.debug(f"[VectorStore] 清除旧向量(可能首次): {e}")

        # 写入新向量
        self.vector_store.add_documents(split_docs)
        logger.info(f"[VectorStore] {os.path.basename(file_path)} 写入 {len(split_docs)} 个 chunk")
        return True, len(split_docs)

    def delete_document_vectors(self, file_path: str):
        """删除指定文件的向量"""
        try:
            self.vector_store._collection.delete(where={"source": {"$eq": file_path}})
            logger.info(f"[VectorStore] 已删除向量: {file_path}")
        except Exception as e:
            logger.warning(f"[VectorStore] 删除向量失败: {file_path} - {e}")

    def get_chunk_count(self) -> int:
        """获取当前 ChromaDB 中的 chunk 总数"""
        return self.vector_store._collection.count()

    def get_all_chunks(self) -> list[dict]:
        """获取所有 chunk (用于 BM25 构建)"""
        results = self.vector_store._collection.get(include=["documents", "metadatas"])
        chunks = []
        for i in range(len(results["ids"])):
            chunks.append({
                "id": results["ids"][i],
                "text": results["documents"][i],
                "metadata": results["metadatas"][i] if results["metadatas"] else {},
            })
        return chunks

    def get_fusion_retriever(self):
        """获取融合检索器 (BM25 + Dense → RRF) — 延迟初始化 BM25"""
        if self._bm25_index is None:
            from kb.bm25_index import BM25SparseIndex
            self._bm25_index = BM25SparseIndex(self, self.kb_store, config=chroma_conf.get("bm25", {}))

        from kb.fusion_retriever import FusionRetriever
        fusion_conf = chroma_conf.get("fusion", {})

        return FusionRetriever(
            vector_store=self.vector_store,
            bm25_index=self._bm25_index,
            embed_model=embed_model,
            k=fusion_conf.get("final_top_k", 5),
            rrf_k=fusion_conf.get("rrf_k", 60),
            dense_top_k=fusion_conf.get("dense_top_k", 10),
            bm25_top_k=fusion_conf.get("bm25_top_k", 10),
        )

    def rebuild_bm25(self):
        """重建 BM25 索引"""
        if self._bm25_index is not None:
            self._bm25_index.rebuild()
