"""
BM25稀疏检索索引
- 启动时从ChromaDB读取全量文档，使用jieba分词后构建BM25Okapi索引
- 索引不单独持久化，重启自动重建（当前语料量级下可接受）
- 文档更新后通过 rebuild() 重建
"""

import jieba
from rank_bm25 import BM25Okapi
from typing import Optional

from utils.config_handler import chroma_conf
from utils.logger_handler import logger


class BM25SparseIndex(object):
    """BM25稀疏检索索引，封装 rank_bm25.BM25Okapi

    从ChromaDB中读取全部已入库文档，使用jieba中文分词后构建BM25索引。
    每次启动自动重建，不单独持久化。
    """

    def __init__(self, vector_store, config: Optional[dict] = None):
        """
        :param vector_store: langchain_chroma.Chroma 向量存储实例
        :param config: BM25参数字典 {k1, b, epsilon}，默认从 chroma.yaml 读取
        """
        self.vector_store = vector_store
        self.config = config or chroma_conf.get('bm25', {})

        # BM25Okapi实例，_build() 后可用
        self.bm25: Optional[BM25Okapi] = None

        # 索引映射：corpus索引 -> ChromaDB文档ID
        self._chunk_ids: list = []

        # 索引映射：corpus索引 -> 原始page_content（用于search时直接返回文本）
        self._documents: list = []

        self._build()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list:
        """使用jieba进行中文分词（精确模式），过滤空白token

        :param text: 待分词文本
        :return: 分词后的词列表
        """
        tokens = list(jieba.cut(text))
        # 过滤纯空白/换行token，保留有意义的词
        return [t for t in tokens if t.strip()]

    def _build(self):
        """从ChromaDB读取全部文档并构建BM25索引

        步骤：
        1. 调用 vector_store.get() 获取全量文档ID和内容
        2. 对每个文档用 jieba.cut 分词
        3. 用分词后的语料库初始化 BM25Okapi
        4. 存储 chunk_ids 映射以便后续获取完整Document
        """
        try:
            # 通过 langchain_chroma 的 get() 获取全量数据
            data = self.vector_store.get(include=['documents'])
        except Exception as exc:
            logger.warning(f"[BM25] 无法从ChromaDB读取文档，索引为空：{str(exc)}")
            self.bm25 = None
            self._chunk_ids = []
            self._documents = []
            return

        ids = data.get('ids', [])
        documents = data.get('documents', [])

        if not ids or not documents:
            logger.info("[BM25] ChromaDB中无文档，BM25索引为空")
            self.bm25 = None
            self._chunk_ids = []
            self._documents = []
            return

        # 存储ID和文档映射
        self._chunk_ids = list(ids)
        self._documents = list(documents)

        # 对每个文档分词
        tokenized_corpus = [self._tokenize(doc) for doc in documents]

        # 初始化BM25Okapi
        # tokenizer=None 因为已经在外部用jieba预分词
        k1 = self.config.get('k1', 1.5)
        b = self.config.get('b', 0.75)
        epsilon = self.config.get('epsilon', 0.25)

        self.bm25 = BM25Okapi(
            tokenized_corpus,
            k1=k1,
            b=b,
            epsilon=epsilon,
        )

        logger.info(f"[BM25] 索引构建完成，共 {len(tokenized_corpus)} 条文档")

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = 10) -> list:
        """BM25检索，返回top-k结果

        :param query: 查询文本
        :param k: 返回结果数量
        :return: [(chunk_id, bm25_score), ...] 按分数降序排列（仅返回分数>0的结果）
        """
        if self.bm25 is None or not self._chunk_ids:
            logger.debug("[BM25] 索引为空，返回空结果")
            return []

        # 查询分词
        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        # 计算BM25分数
        scores = self.bm25.get_scores(tokenized_query)

        # 按分数降序排列，过滤零分
        ranked = sorted(
            [(self._chunk_ids[i], scores[i]) for i in range(len(scores)) if scores[i] > 0],
            key=lambda x: x[1],
            reverse=True,
        )

        return ranked[:k]

    def rebuild(self):
        """重建BM25索引（文档更新后调用）

        清空现有索引，从ChromaDB重新读取全部文档并构建。
        """
        logger.info("[BM25] 开始重建索引...")
        self._chunk_ids = []
        self._documents = []
        self._build()
        logger.info("[BM25] 索引重建完成")


if __name__ == '__main__':
    # 自测：需要先有已入库的ChromaDB数据
    from langchain_chroma import Chroma
    from model.factory import embed_model
    from utils.path_tool import get_abs_path

    vs = Chroma(
        collection_name=chroma_conf['collection_name'],
        embedding_function=embed_model,
        persist_directory=get_abs_path(chroma_conf['persist_directory']),
    )

    bm25_index = BM25SparseIndex(vs)

    print(f"索引中文档数：{len(bm25_index._chunk_ids)}")

    # 测试搜索
    results = bm25_index.search("决策树", k=5)
    print(f"\n搜索 '决策树' Top 5:")
    for i, (chunk_id, score) in enumerate(results):
        # 找到对应的文档内容预览
        try:
            idx = bm25_index._chunk_ids.index(chunk_id)
            preview = bm25_index._documents[idx][:80]
        except (ValueError, IndexError):
            preview = "<无法获取预览>"
        print(f"  {i+1}. id={chunk_id[:16]}... score={score:.4f} preview={preview}...")
