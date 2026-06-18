"""
融合检索器：BM25稀疏检索 + Dense稠密检索 → RRF融合 → Top K

流程：
  1. BM25检索 top bm25_top_k 条
  2. Dense向量检索 top dense_top_k 条
  3. RRF（Reciprocal Rank Fusion）融合去重重排
  4. 返回最终 top final_top_k 个Document
"""

from collections import defaultdict
from typing import Optional
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from utils.config_handler import chroma_conf
from utils.logger_handler import logger


class FusionRetriever(object):
    """融合检索器：BM25 + Dense → RRF → Top K"""

    def __init__(self, vector_store,
                 bm25_index,
                 embed_model: Embeddings,
                 k: int = 5,
                 rrf_k: int = 60,
                 dense_top_k: int = 10,
                 bm25_top_k: int = 10):
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

    def retrieve(self, query: str) -> list:
        """执行融合检索

        :param query: 用户查询文本
        :return: list[Document]，按RRF分数降序排列
        """
        # 1. 双路并行检索
        bm25_ranked = self._bm25_search(query)
        dense_ranked = self._dense_search(query)

        logger.debug(
            f"[Fusion] BM25召回={len(bm25_ranked)}条, "
            f"Dense召回={len(dense_ranked)}条"
        )

        # 2. RRF融合
        fused = self._rrf_fusion(dense_ranked, bm25_ranked)
        top_ids = [chunk_id for chunk_id, _ in fused[:self.k]]

        logger.debug(f"[Fusion] RRF融合后选取Top {len(top_ids)}条")

        # 3. 获取完整Document对象
        docs = self._fetch_documents(top_ids)

        return docs

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _dense_search(self, query: str) -> list:
        """Dense稠密向量检索

        先用 self.embed_model 将查询转为向量，再通过 ChromaDB 底层
        collection.query(query_embeddings=...) 获取带ID的排序结果。
        不直接传 query_texts 是为了避免 chromadb 使用其内置的（不匹配的）
        embedding function 而非我们指定的 DashScope 嵌入模型。

        :param query: 用户查询
        :return: [(chunk_id, rank_position), ...] rank从1开始
        """
        try:
            # 用我们自己的 embed_model 将查询转为向量，避免 chromadb
            # 使用内置 OnnxEmbeddingFunction（维度不匹配）
            query_embedding = self.embed_model.embed_query(query)
            results = self.vector_store._collection.query(
                query_embeddings=[query_embedding],
                n_results=self.dense_top_k,
                include=['documents', 'metadatas'],
            )
        except Exception as exc:
            logger.warning(f"[Fusion] Dense检索失败：{str(exc)}")
            return []

        ids = results.get('ids', [[]])[0]
        # rank从1开始
        return [(chunk_id, rank) for rank, chunk_id in enumerate(ids, start=1)]

    def _bm25_search(self, query: str) -> list:
        """BM25稀疏检索

        :param query: 用户查询
        :return: [(chunk_id, rank_position), ...] rank从1开始
        """
        scored_results = self.bm25_index.search(query, k=self.bm25_top_k)
        # 转换 (id, score) -> (id, rank)，rank从1开始
        return [(chunk_id, rank) for rank, (chunk_id, _) in enumerate(scored_results, start=1)]

    def _rrf_fusion(self, dense_ranked: list,
                    bm25_ranked: list) -> list:
        """RRF（Reciprocal Rank Fusion）融合算法

        对每个出现在任一结果列表中的文档计算：
            RRF_score(d) = Σ 1 / (rrf_k + rank_i(d))

        其中 rank_i 从1开始计数。

        :param dense_ranked: [(chunk_id, rank), ...]
        :param bm25_ranked: [(chunk_id, rank), ...]
        :return: [(chunk_id, rrf_score), ...] 按RRF分数降序排列
        """
        scores: dict = defaultdict(float)

        # Dense检索贡献
        for chunk_id, rank in dense_ranked:
            scores[chunk_id] += 1.0 / (self.rrf_k + rank)

        # BM25检索贡献
        for chunk_id, rank in bm25_ranked:
            scores[chunk_id] += 1.0 / (self.rrf_k + rank)

        # 按分数降序排列
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        return fused

    def _fetch_documents(self, chunk_ids: list) -> list:
        """根据chunk_id列表从ChromaDB批量获取完整Document对象

        :param chunk_ids: ChromaDB文档ID列表
        :return: list[Document]，保持传入顺序
        """
        if not chunk_ids:
            return []

        try:
            data = self.vector_store._collection.get(
                ids=chunk_ids,
                include=['documents', 'metadatas'],
            )
        except Exception as exc:
            logger.error(f"[Fusion] 获取文档失败：{str(exc)}")
            return []

        # 按chunk_ids顺序重建Document列表（_collection.get不保证顺序）
        id_to_doc = {}
        id_to_meta = {}
        for i, cid in enumerate(data.get('ids', [])):
            id_to_doc[cid] = data['documents'][i] if data.get('documents') else ''
            id_to_meta[cid] = data['metadatas'][i] if data.get('metadatas') else {}

        docs = []
        for cid in chunk_ids:
            if cid in id_to_doc:
                docs.append(Document(
                    page_content=id_to_doc[cid],
                    metadata=id_to_meta.get(cid, {}),
                ))

        return docs


if __name__ == '__main__':
    # 自测：对比三种检索方式
    from langchain_chroma import Chroma
    from model.factory import embed_model
    from utils.path_tool import get_abs_path
    from rag.bm25_index import BM25SparseIndex

    vs = Chroma(
        collection_name=chroma_conf['collection_name'],
        embedding_function=embed_model,
        persist_directory=get_abs_path(chroma_conf['persist_directory']),
    )

    bm25 = BM25SparseIndex(vs)
    fusion_conf = chroma_conf.get('fusion', {})

    retriever = FusionRetriever(
        vector_store=vs,
        bm25_index=bm25,
        embed_model=embed_model,
        k=fusion_conf.get('final_top_k', 5),
        rrf_k=fusion_conf.get('rrf_k', 60),
        dense_top_k=fusion_conf.get('dense_top_k', 10),
        bm25_top_k=fusion_conf.get('bm25_top_k', 10),
    )

    query = "小户型适合哪种扫地机器人"
    print(f"查询: {query}\n")

    # BM25 only
    bm25_results = bm25.search(query, k=5)
    print("=== BM25 Only Top 5 ===")
    for i, (cid, score) in enumerate(bm25_results):
        # 获取预览
        data = vs._collection.get(ids=[cid], include=['documents'])
        if data['ids']:
            preview = data['documents'][0][:100].replace('\n', ' ')
            print(f"  {i+1}. score={score:.4f} | {preview}...")
    print()

    # Dense only
    print("=== Dense Only Top 5 ===")
    query_embedding = embed_model.embed_query(query)
    dense_results = vs._collection.query(
        query_embeddings=[query_embedding], n_results=5, include=['documents']
    )
    for i, doc_text in enumerate(dense_results['documents'][0]):
        preview = doc_text[:100].replace('\n', ' ')
        print(f"  {i+1}. {preview}...")
    print()

    # RRF Fusion
    print("=== RRF Fusion Top 5 ===")
    fused_docs = retriever.retrieve(query)
    for i, doc in enumerate(fused_docs):
        preview = doc.page_content[:100].replace('\n', ' ')
        print(f"  {i+1}. {preview}...")
