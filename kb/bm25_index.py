"""
每个知识库独立的 BM25 稀疏索引 — 支持持久化加速启动

构建时优先从 kb_store 读取缓存的分词结果，避免重新对全量文档进行 jieba 分词。
当缓存不可用或 chunk 数量不匹配时，回退到从 vector_store 读取所有 chunk 并分词。
分词结果和元数据持久化到 kb_store，下次启动可在数秒内完成索引恢复。
"""

import os
import json
import math
from typing import Optional

from core.logger import logger
from rank_bm25 import BM25Okapi


class BM25SparseIndex:
    """每个知识库独立的 BM25 稀疏索引

    封装 rank_bm25.BM25Okapi，支持:
    - 持久化 token 缓存加速启动
    - 从 vector_store（ChromaDB）回退重建
    - 强制重建
    - BM25 参数配置 (k1, b, epsilon)
    """

    def __init__(self, vector_store, kb_store, config: dict = None):
        """
        :param vector_store: VectorStoreService 实例用于该 KB
            （提供 get_all_chunks / get_chunk_count 接口）
        :param kb_store: KBStore 实例用于该 KB
            （提供 get_bm25_tokens / save_bm25_tokens / get_bm25_meta / set_bm25_meta 接口）
        :param config: BM25 参数字典 {k1, b, epsilon}，不传时使用默认值
        """
        self.vector_store = vector_store
        self.kb_store = kb_store
        self.config = config or {}

        # BM25Okapi 实例，build() 后可用
        self.bm25: Optional[BM25Okapi] = None

        # 索引映射：corpus 索引 -> ChromaDB 文档 ID
        self._chunk_ids: list = []

        # 构建索引
        self.build()

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def build(self):
        """构建 BM25 索引 — 优先从持久化 token 恢复，否则回退到 ChromaDB

        流程:
        1. 从 kb_store.get_bm25_tokens() 读取缓存的 token 数据
        2. 若 tokens 存在且数量与 vector_store 中 chunk 数一致，直接构建（快速）
        3. 否则回退到从 vector_store.get_all_chunks() 读取全量文档，
           对每篇文档分词后持久化到 kb_store，然后构建索引
        4. 将 avg_doc_length, total_docs, k1, b, epsilon 保存到 bm25_meta
        """
        try:
            # 1. 尝试从持久化 token 缓存恢复
            cached_tokens = self.kb_store.get_bm25_tokens()

            if cached_tokens:
                try:
                    chunk_count = self.vector_store.get_chunk_count()
                except Exception:
                    # 如果无法获取 chunk 数量，信任缓存
                    chunk_count = len(cached_tokens)

                if len(cached_tokens) == chunk_count:
                    logger.info(
                        f"[BM25] 从持久化 token 恢复索引 "
                        f"({len(cached_tokens)} 条，耗时约数秒)"
                    )
                    self._build_from_tokens(cached_tokens)
                    return

            # 2. 缓存不可用或数量不匹配，从 vector_store 回退重建
            logger.info(
                "[BM25] 持久化 token 不可用或数量不匹配，"
                "从 ChromaDB 重新读取并分词"
            )
            self._build_from_vector_store()

        except Exception as exc:
            logger.warning(
                f"[BM25] 构建索引失败，索引为空：{exc}"
            )
            self.bm25 = None
            self._chunk_ids = []

    def rebuild(self):
        """强制重建 BM25 索引

        清空持久化 token，重新从 vector_store 读取全量文档，
        逐个分词后保存 token 到 kb_store，最后构建 BM25Okapi 实例。
        """
        logger.info("[BM25] 开始强制重建索引...")
        self._chunk_ids = []
        self.bm25 = None
        self._build_from_vector_store()
        logger.info("[BM25] 索引重建完成")

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """BM25 检索，返回 top-k 结果

        :param query: 查询文本
        :param k: 返回结果数量
        :return: [(chunk_id, bm25_score), ...] 按分数降序排列
                 仅返回分数 > 0 的结果
        """
        if self.bm25 is None or not self._chunk_ids:
            logger.debug("[BM25] 索引为空，返回空结果")
            return []

        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        scores = self.bm25.get_scores(tokenized_query)

        ranked = sorted(
            [
                (self._chunk_ids[i], scores[i])
                for i in range(len(scores))
                if scores[i] > 0
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        return ranked[:k]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """使用 jieba 进行中文分词（搜索模式），过滤空白 token

        :param text: 待分词文本
        :return: 分词后的词列表
        """
        import jieba

        tokens = list(jieba.cut_for_search(text))
        # 过滤纯空白/换行 token，保留有意义的词
        return [t for t in tokens if t.strip()]

    def _build_from_tokens(self, tokens_list: list[dict]):
        """从持久化的 token 数据构建 BM25 索引

        :param tokens_list: list[dict]，每个条目包含:
            - chunk_id: str  — ChromaDB 文档 ID
            - tokens: str    — 空格分隔的已分词词语
            - doc_length: int — 分词后词语数量
        其中 tokens 字段是已通过 jieba 分词并以空格连接的结果，
        此处直接用 `.split()` 还原为 list[str] 输入 BM25Okapi。
        """
        self._chunk_ids = []
        tokenized_corpus = []

        for entry in tokens_list:
            chunk_id = entry["chunk_id"]
            tokens_str = entry["tokens"]

            self._chunk_ids.append(chunk_id)
            tokenized_corpus.append(tokens_str.split())

        if not tokenized_corpus:
            logger.info("[BM25] 无有效 token 数据，索引为空")
            self.bm25 = None
            return

        k1 = self.config.get("k1", 1.5)
        b = self.config.get("b", 0.75)
        epsilon = self.config.get("epsilon", 0.25)

        self.bm25 = BM25Okapi(
            tokenized_corpus,
            k1=k1,
            b=b,
            epsilon=epsilon,
        )

        logger.info(
            f"[BM25] 从持久化 token 构建完成，共 {len(tokenized_corpus)} 条文档"
        )

    def _build_from_vector_store(self):
        """从 vector_store 读取全量文档，分词并持久化，构建 BM25 索引

        步骤:
        1. 调用 vector_store.get_all_chunks() 获取所有 chunk
        2. 对每个 chunk 的文本用 jieba 分词
        3. 将分词结果保存到 kb_store
        4. 用分词后的语料库初始化 BM25Okapi
        5. 将 avg_doc_length, total_docs 等元数据写入 kb_store bm25_meta
        """
        try:
            chunks = self.vector_store.get_all_chunks()
        except Exception as exc:
            logger.warning(
                f"[BM25] 无法从 vector_store 读取文档，索引为空：{exc}"
            )
            self.bm25 = None
            self._chunk_ids = []
            return

        if not chunks:
            logger.info("[BM25] vector_store 中无文档，BM25 索引为空")
            self.bm25 = None
            self._chunk_ids = []
            return

        self._chunk_ids = []
        tokenized_corpus = []
        total_doc_length = 0

        for chunk in chunks:
            chunk_id = chunk["id"]
            text = chunk.get("text", "")

            self._chunk_ids.append(chunk_id)

            # 分词
            tokens = self._tokenize(text)
            doc_length = len(tokens)
            total_doc_length += doc_length

            tokenized_corpus.append(tokens)

            # 持久化 token 到 kb_store
            tokens_str = " ".join(tokens)
            doc_preview = text[:100] if text else ""
            self.kb_store.save_bm25_tokens(
                chunk_id,
                tokens_str,
                doc_length,
                doc_preview,
            )

        if not tokenized_corpus:
            self.bm25 = None
            return

        k1 = self.config.get("k1", 1.5)
        b = self.config.get("b", 0.75)
        epsilon = self.config.get("epsilon", 0.25)

        self.bm25 = BM25Okapi(
            tokenized_corpus,
            k1=k1,
            b=b,
            epsilon=epsilon,
        )

        # 保存元数据到 kb_store bm25_meta 表
        total_docs = len(tokenized_corpus)
        avg_doc_length = total_doc_length / total_docs if total_docs > 0 else 0.0

        self.kb_store.set_bm25_meta("avg_doc_length", str(avg_doc_length))
        self.kb_store.set_bm25_meta("total_docs", str(total_docs))
        self.kb_store.set_bm25_meta("k1", str(k1))
        self.kb_store.set_bm25_meta("b", str(b))
        self.kb_store.set_bm25_meta("epsilon", str(epsilon))

        logger.info(
            f"[BM25] 索引构建完成，共 {total_docs} 条文档，"
            f"avg_doc_length={avg_doc_length:.2f}"
        )
