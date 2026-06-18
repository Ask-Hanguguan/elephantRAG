from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

from model.factory import chat_model
from rag.vector_store import VectorStoreService
from rag.segment_extractor import SegmentExtractor
from langchain_core.prompts import PromptTemplate

from utils.config_handler import prompts_conf, chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class RagSummarizeService:
    # 类变量缓存，所有实例共用
    _PROMPT_TEXT: str = None

    def __init__(self, vector_store: VectorStoreService):
        self.vector_store = vector_store
        # 融合检索器（BM25 + Dense → RRF → Top K）
        self.fusion_retriever = self.vector_store.get_fusion_retriever()
        # 段落提取器（合并相邻chunk为连续段落）
        self.segment_extractor = SegmentExtractor()
        self.prompt_text = self._load_prompt_text()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.chain = self._init_chain()

    def _load_prompt_text(self):
        if self._PROMPT_TEXT is not None:
            # 避免重复创建对象的重复读文件加载，从缓存读取
            return self._PROMPT_TEXT

        path = get_abs_path(prompts_conf["rag_summarize_prompt_path"])
        try:
            with open(path,'r',encoding='utf-8') as f:
                prompt_text = f.read().strip()
        except PermissionError:
            logger.error(f"无权限读取提示词文件：{path}")
            raise PermissionError(f"无权限读取提示词文件：{path}")
        except UnicodeDecodeError:
            logger.error(f"提示词文件编码错误（需UTF-8）：{path}")
            raise ValueError(f"提示词文件编码错误（需UTF-8）：{path}")
        except Exception as e:
            logger.error(f"读取提示词文件失败：{str(e)}")
            raise RuntimeError(f"读取提示词文件失败：{str(e)}")

        if not prompt_text:
            logger.error(f"提示词文件内容为空：{path}")
            raise ValueError(f"提示词文件内容为空：{path}")

        # 记录缓存
        self._PROMPT_TEXT = prompt_text
        return prompt_text

    def _init_chain(self):
        chain = self.prompt_template | self.model |StrOutputParser()
        return chain

    def retriever_docs(self, query: str) -> list[Document]:
        # Step 1: 融合检索（BM25 + Dense → RRF → Top K）
        fused_docs = self.fusion_retriever.retrieve(query)

        # Step 2: 段落提取（合并同一文档来源的相邻chunk，依赖CCH写入的chunk_index）
        segment_enabled = chroma_conf.get('segment', {}).get('enabled', True)
        if segment_enabled:
            # 检测chunk_index是否存在（CCH关闭时不会写入该字段）
            has_chunk_index = any(
                doc.metadata.get('chunk_index') is not None
                for doc in fused_docs
            )
            if not has_chunk_index:
                logger.warning(
                    "[检索] 段落合并已开启(segment.enabled=true)，但文档缺少chunk_index "
                    "元数据（CCH可能未开启），跳过合并"
                )
                return fused_docs

            segments = self.segment_extractor.extract_segments(fused_docs)
            return segments

        return fused_docs

    def rag_summarize(self, query: str) -> str:
        '''
        总结召回结果，注入提示词模板，调用model，返回输出
        :param query: 用户问题
        :return: 模型最终输出的str
        '''
        input_dict = {}

        context_docs = self.retriever_docs(query)
        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            # 标记合并信息（段落提取后的相邻chunk合并）
            merge_info = ""
            if doc.metadata.get('merged_from', 1) > 1:
                chunk_range = doc.metadata.get('chunk_range', '?')
                merge_info = f" [合并自{doc.metadata['merged_from']}个连续片段({chunk_range})]"

            context += (
                f"【参考资料{counter}】{merge_info}\n"
                f"{doc.page_content}\n"
            )
        input_dict["input"] = query
        input_dict["context"] = context

        return self.chain.invoke(input_dict)


if __name__ == '__main__':
    vs = VectorStoreService()
    rag = RagSummarizeService(vs)

    print(rag.rag_summarize("什么是K-Means聚类算法？"))
