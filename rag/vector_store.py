import os.path
from typing import Optional

from utils.logger_handler import logger
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from model.factory import embed_model
from utils.config_handler import chroma_conf
from utils.file_handler import listdir_with_allowed_type, get_file_md5_hex, docling_loader
from utils.path_tool import get_abs_path
from rag.md5_store import MD5Store
from rag.cch_preprocessor import CCHPreprocessor

class VectorStoreService(object):
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_conf['collection_name'],
            embedding_function=embed_model,
            persist_directory=get_abs_path(chroma_conf['persist_directory']),
        )

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size = chroma_conf['chunk_size'],
            chunk_overlap = chroma_conf['chunk_overlap'],
            separators = chroma_conf['separators'],
            length_function=len,
        )

        self.md5_store = MD5Store()

        # CCH预处理器（LLM延迟加载）
        self.cch_preprocessor = CCHPreprocessor()

        # BM25稀疏索引（延迟初始化，首次调用 get_fusion_retriever 时构建）
        self._bm25_index = None

    def load_document(self):

        def get_file_document(read_path:  str):
            return docling_loader(read_path)

        # 获取一个可操作文件路径列表
        allowed_file_path = listdir_with_allowed_type(
            get_abs_path(chroma_conf['data_path']),
            tuple(chroma_conf['allow_knowledge_file_type']),
        )

        for path in allowed_file_path:
            md5_hex = get_file_md5_hex(path)

            if not md5_hex: # 处理MD5计算失败的情况
                logger.warning(f"[加载知识库] {path} MD5计算失败，跳过")
                continue

            if self.md5_store.is_existing_md5(md5_hex):
                logger.info(f"[加载知识库] {path} 内容已经存在于知识库，跳过")
                continue

            try:
                documents: list[Document] = get_file_document(path)

                if not documents:
                    logger.warning(f"[加载知识库] {path} 无有效文本内容，跳过")
                    continue

                # ============================================================
                # CCH预处理（分块前提取标题/摘要/章节，分块后为每个chunk添加头部）
                # ============================================================
                cch_enabled = chroma_conf.get('cch', {}).get('enabled', True)

                if cch_enabled:
                    full_text = "\n".join([d.page_content for d in documents])
                    cch_meta = self.cch_preprocessor.preprocess(path, full_text)
                    title = cch_meta['title']
                    summary = cch_meta['summary']
                    section_map = cch_meta['section_map']
                    logger.debug(f"[加载知识库] CCH预处理完成：标题={title}")

                split_documents: list[Document] = self.splitter.split_documents(documents)

                if not split_documents:
                    logger.warning(f"[加载知识库] {path} 分片后无内容，跳过")
                    continue

                # ============================================================
                # CCH头部注入：为每个chunk添加文档上下文 + chunk_index元数据
                # ============================================================
                if cch_enabled:
                    for i, chunk in enumerate(split_documents):
                        section_path = self.cch_preprocessor.determine_section(
                            chunk.page_content, full_text, section_map
                        )
                        chunk.page_content = (
                            self.cch_preprocessor.build_cch_header(
                                title, summary, section_path
                            )
                            + chunk.page_content
                        )
                        chunk.metadata['chunk_index'] = i
                        chunk.metadata['title'] = title
                        chunk.metadata['summary'] = summary
                        chunk.metadata['section_path'] = section_path
                else:
                    logger.info(
                        "[加载知识库] CCH未启用(cchenabled=false)，文档未写入chunk_index，"
                        "段落合并(segment)功能将不可用"
                    )

                self.vector_store.add_documents(split_documents)

                self.md5_store.add_md5(md5_hex)

                logger.info(f"[加载知识库] {path} 内容加载成功（共{len(split_documents)}个chunk）")
            except Exception as e:
                # exc_info为True会记录详细报错堆栈，False仅记录报错str
                logger.error(f"[加载知识库] {path} 加载失败：{str(e)}", exc_info=True)
                continue

        # ============================================================
        # 文档加载完成后重建BM25索引（如有新文档入库）
        # ============================================================
        if self._bm25_index is not None:
            self._bm25_index.rebuild()
            logger.info("[加载知识库] BM25索引已重建")

    def get_retriever(self):
        """获取原始稠密检索器（向后兼容）"""
        return self.vector_store.as_retriever(search_kwargs={"k":chroma_conf['k']})

    def get_fusion_retriever(self):
        """获取融合检索器（BM25 + Dense → RRF → Top K）

        延迟初始化BM25索引（首次调用时从ChromaDB构建）。
        配置从 chroma.yaml 的 fusion / bm25 段读取。
        """
        if self._bm25_index is None:
            from rag.bm25_index import BM25SparseIndex
            self._bm25_index = BM25SparseIndex(
                self.vector_store,
                config=chroma_conf.get('bm25', {}),
            )

        from rag.fusion_retriever import FusionRetriever
        fusion_conf = chroma_conf.get('fusion', {})

        return FusionRetriever(
            vector_store=self.vector_store,
            bm25_index=self._bm25_index,
            embed_model=embed_model,
            k=fusion_conf.get('final_top_k', 5),
            rrf_k=fusion_conf.get('rrf_k', 60),
            dense_top_k=fusion_conf.get('dense_top_k', 10),
            bm25_top_k=fusion_conf.get('bm25_top_k', 10),
        )

if __name__ == '__main__':
    store = VectorStoreService()
    store.load_document()

    restriever = store.get_retriever()

    res = restriever.invoke("韩语单词学习卡片")
    for r in res:
        print(r.page_content)
        print("-" * 20)





