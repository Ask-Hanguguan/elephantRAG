import os.path
from typing import Optional

from utils.logger_handler import logger
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from model.factory import embed_model
from utils.config_handler import chroma_conf
from utils.file_handler import get_file_md5_hex, docling_loader
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

        def get_file_document(read_path: str):
            return docling_loader(read_path)

        # ================================================================
        # Phase 1: 构建当前文件清单 {绝对路径: MD5}
        # ================================================================
        data_path = get_abs_path(chroma_conf['data_path'])
        allowed_exts = tuple(chroma_conf['allow_knowledge_file_type'])

        if not os.path.isdir(data_path):
            logger.error(f"[加载知识库] 数据目录不存在：{data_path}")
            return

        current_files = {}
        for fname in os.listdir(data_path):
            if not fname.endswith(allowed_exts):
                continue
            fpath = os.path.join(data_path, fname)
            md5 = get_file_md5_hex(fpath)
            if md5:
                current_files[fpath] = md5

        if not current_files:
            logger.info("[加载知识库] data/ 目录无有效文件")
            return

        # ================================================================
        # Phase 2: 首次迁移 → 尝试用旧MD5匹配当前文件，避免全量重入库
        # ================================================================
        if self.md5_store.old_md5s:
            old_set = set(self.md5_store.old_md5s)
            matched = 0
            for path, md5 in current_files.items():
                if md5 in old_set:
                    self.md5_store.add_md5(md5, path)
                    matched += 1
            if matched:
                logger.info(
                    f"[加载知识库] 匹配旧MD5记录 {matched}/{len(current_files)} 个文件，避免重入库"
                )

        # ================================================================
        # Phase 3: 与 MD5Store 比对，分类变更
        # ================================================================
        stored = self.md5_store.get_all_records()  # {path: md5}

        deleted = {p for p in stored if p not in current_files}
        changed = {p for p in current_files if p in stored and stored[p] != current_files[p]}
        added = {p for p in current_files if p not in stored}
        # unchanged = 自然跳过，无需处理

        any_change = bool(deleted or changed or added)

        # ================================================================
        # Phase 4: 清理已删除/已变更的文件（先删后加）
        # ================================================================
        to_remove = deleted | changed
        for path in to_remove:
            try:
                # 从 ChromaDB 删除（按 source 路径匹配 metadata）
                self.vector_store._collection.delete(where={"source": {"$eq": path}})
                # 从 MD5Store 删除
                self.md5_store.delete_by_path(path)
                logger.info(f"[加载知识库] 已移除：{os.path.basename(path)}")
            except Exception as e:
                logger.warning(f"[加载知识库] 移除失败：{path} - {str(e)}")

        # ================================================================
        # Phase 5: 添加新文件/变更的文件
        # ================================================================
        cch_enabled = chroma_conf.get('cch', {}).get('enabled', True)

        to_add = added | changed
        for path in to_add:
            md5_hex = current_files[path]

            try:
                documents: list[Document] = get_file_document(path)

                if not documents:
                    logger.warning(f"[加载知识库] {path} 无有效文本内容，跳过")
                    continue

                # CCH预处理（分块前提取标题/摘要/章节）
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

                # 为每个 chunk 注入元数据 + CCH头部
                for i, chunk in enumerate(split_documents):
                    # 级联同步必需的元数据（无论CCH是否开启）
                    chunk.metadata['source'] = path
                    chunk.metadata['file_md5'] = md5_hex

                    if cch_enabled:
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

                if not cch_enabled:
                    logger.info(
                        "[加载知识库] CCH未启用(cch.enabled=false)，文档未写入chunk_index，"
                        "段落合并(segment)功能将不可用"
                    )

                self.vector_store.add_documents(split_documents)

                self.md5_store.add_md5(md5_hex, path)

                logger.info(f"[加载知识库] {path} 加载成功（共{len(split_documents)}个chunk）")
            except Exception as e:
                logger.error(f"[加载知识库] {path} 加载失败：{str(e)}", exc_info=True)
                continue

        # ================================================================
        # Phase 6: 重建BM25索引（有变更时才重建）
        # ================================================================
        if any_change and self._bm25_index is not None:
            self._bm25_index.rebuild()
            logger.info("[加载知识库] BM25索引已重建")
        elif not any_change:
            logger.info("[加载知识库] 无文件变更，跳过BM25重建")

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

    # res = restriever.invoke("空间滤波")
    # for r in res:
    #     print(r.page_content)
    #     print("-" * 20)





