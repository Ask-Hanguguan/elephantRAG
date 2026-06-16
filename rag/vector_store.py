import os.path
from utils.logger_handler import logger
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from model.factory import embed_model
from utils.config_handler import chroma_conf
from utils.file_handler import txt_loader, listdir_with_allowed_type, get_file_md5_hex, pdf_loader
from utils.path_tool import get_abs_path
from rag.md5_store import MD5Store

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

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k":chroma_conf['k']})

    def load_document(self):

        def get_file_document(read_path:  str):
            if read_path.endswith('.txt'):
                return txt_loader(read_path)
            elif read_path.endswith('.pdf'):
                return pdf_loader(read_path)
            else:
                return []

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

                split_documents: list[Document] = self.splitter.split_documents(documents)

                if not split_documents:
                    logger.warning(f"[加载知识库] {path} 分片后无内容，跳过")
                    continue

                self.vector_store.add_documents(split_documents)

                self.md5_store.add_md5(md5_hex)

                logger.info(f"[加载知识库] {path} 内容加载成功")
            except Exception as e:
                # exc_info为True会记录详细报错堆栈，False仅记录报错str
                logger.error(f"[加载知识库] {path} 加载失败：{str(e)}", exc_info=True)
                continue

if __name__ == '__main__':
    store = VectorStoreService()
    store.load_document()

    restriever = store.get_retriever()

    res = restriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-" * 20)





