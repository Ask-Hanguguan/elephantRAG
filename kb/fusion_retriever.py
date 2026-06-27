"""
融合检索器 — BM25 + Dense → RRF 融合 → Top K

与旧版相比仅调整了导入路径，逻辑不变。
"""

from collections import defaultdict
from typing import Any, Optional

from core.config import chroma_conf
from core.logger import logger
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings


class FusionRetriever:
    """融合检索器：BM25 + Dense → RRF → Top K"""

    def __init__(
        self,
        vector_store: Chroma,
        bm25_index,
        embed_model: Embeddings,
        k: int = 5,
        rrf_k: int = 60,
        dense_top_k: int = 10,
        bm25_top_k: int = 10,
    ):
        """
        :param vector_store: langchain_chroma.Chroma 向量存储实例
        :param bm25_index: BM25SparseIndex 稀疏索引实例
        :param embed_model: 嵌入模型，用于稠密查询向量化
        :param k: 最终返回的文档数量
        :param rrf_k: RRF算法中的k参数（默认60）
        :param dense_top_k: Dense稠密检索候选数量
        :param bm25_top_k: BM25稀疏检索候选数量
        """
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.embed_model = embed_model
        self.k = k
        self.rrf_k = rrf_k
        self.dense_top_k = dense_top_k
        self.bm25_top_k = bm25_top_k

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def invoke(self, query: str) -> list[dict]:
        """执行融合检索

        :param query: 用户查询文本
        :return: list[dict]，按RRF分数降序排列，每项含
                 source, score, chunk_id, text, metadata
        """
        # 1. Dense 稠密检索
        dense_results = self._dense_search(query, k=self.dense_top_k)

        # 2. BM25 稀疏检索
        bm25_results = self._bm25_search(query, k=self.bm25_top_k)

        logger.debug(
            f"[Fusion] Dense召回={len(dense_results)}条, "
            f"BM25召回={len(bm25_results)}条"
        )

        # 3. RRF 融合
        fused = self._rrf_fusion(dense_results, bm25_results)
        top_fused = fused[: self.k]

        logger.debug(f"[Fusion] RRF融合后选取Top {len(top_fused)}条")

        # 4. 获取完整文档内容并返回
        enriched = self._fetch_documents(top_fused)

        return enriched

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _dense_search(self, query: str, k: int) -> list[dict]:
        """Dense稠密向量检索

        用 self.embed_model 将查询转为向量，再通过 Chroma 的
        similarity_search_by_vector_with_relevance_scores 获取带相关性分数的结果。

        :param query: 用户查询
        :param k: 返回候选数量
        :return: list[dict]，每项含 {chunk_id, text, score, metadata}
        """
        try:
            query_embedding = self.embed_model.embed_query(query)
            scored_docs = (
                self.vector_store.similarity_search_by_vector_with_relevance_scores(
                    query_embedding, k=k
                )
            )
        except Exception as exc:
            logger.warning(f"[Fusion] Dense检索失败：{exc}")
            return []

        results = []
        for doc, score in scored_docs:
            results.append(
                {
                    "chunk_id": doc.metadata.get("chunk_id", doc.id if hasattr(doc, "id") else ""),
                    "text": doc.page_content,
                    "score": score,
                    "metadata": doc.metadata,
                }
            )
        return results

    def _bm25_search(self, query: str, k: int) -> list[dict]:
        """BM25稀疏检索

        :param query: 用户查询
        :param k: 返回候选数量
        :return: list[dict]，每项含 {chunk_id, score}
        """
        scored_results = self.bm25_index.search(query, k=k)
        results = [
            {"chunk_id": chunk_id, "score": score}
            for chunk_id, score in scored_results
        ]
        return results

    def _rrf_fusion(
        self, dense: list[dict], bm25: list[dict]
    ) -> list[tuple[str, float]]:
        """RRF（Reciprocal Rank Fusion）融合算法

        对每个出现在任一结果列表中的文档计算：
            RRF_score(d) = Σ 1 / (rrf_k + rank_i(d))

        其中 rank_i 从1开始计数，基于 score 降序排列确定。

        :param dense: Dense检索结果 list[dict]，每项含 {chunk_id, ...}
        :param bm25: BM25检索结果 list[dict]，每项含 {chunk_id, ...}
        :return: [(chunk_id, rrf_score), ...] 按RRF分数降序排列
        """
        scores: dict[str, float] = defaultdict(float)

        # Dense检索贡献 — 按 score 降序排列确定 rank
        dense_sorted = sorted(dense, key=lambda x: x.get("score", 0), reverse=True)
        for rank, item in enumerate(dense_sorted, start=1):
            chunk_id = item["chunk_id"]
            scores[chunk_id] += 1.0 / (self.rrf_k + rank)

        # BM25检索贡献 — 按 score 降序排列确定 rank
        bm25_sorted = sorted(bm25, key=lambda x: x.get("score", 0), reverse=True)
        for rank, item in enumerate(bm25_sorted, start=1):
            chunk_id = item["chunk_id"]
            scores[chunk_id] += 1.0 / (self.rrf_k + rank)

        # 按分数降序排列
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return fused

    def _fetch_documents(self, fused: list[tuple[str, float]]) -> list[dict]:
        """根据 RRF 融合结果从 ChromaDB 批量获取完整文档内容

        :param fused: [(chunk_id, rrf_score), ...] 按分数降序排列
        :return: list[dict]，每项含
                 {source, score, chunk_id, text, metadata}
        """
        if not fused:
            return []

        chunk_ids = [item[0] for item in fused]
        score_map = {item[0]: item[1] for item in fused}

        try:
            data = self.vector_store._collection.get(
                ids=chunk_ids,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.error(f"[Fusion] 获取文档失败：{exc}")
            return []

        # 按 chunk_ids 顺序重建（_collection.get 不保证顺序）
        id_to_doc: dict[str, str] = {}
        id_to_meta: dict[str, dict] = {}
        for i, cid in enumerate(data.get("ids", [])):
            id_to_doc[cid] = (
                data["documents"][i] if data.get("documents") else ""
            )
            id_to_meta[cid] = (
                data["metadatas"][i] if data.get("metadatas") else {}
            )

        enriched = []
        for cid in chunk_ids:
            if cid in id_to_doc:
                enriched.append(
                    {
                        "chunk_id": cid,
                        "text": id_to_doc[cid],
                        "metadata": id_to_meta.get(cid, {}),
                        "score": score_map.get(cid, 0.0),
                        "source": id_to_meta.get(cid, {}).get(
                            "source", "unknown"
                        ),
                    }
                )
            else:
                logger.warning(
                    f"[Fusion] chunk_id={cid} 在 ChromaDB 中未找到"
                )

        return enriched
