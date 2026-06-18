import os

from langchain_core.tools import tool
from rag.vector_store import VectorStoreService
from rag.rag_service import RagSummarizeService
from utils.config_handler import agent_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path

vector_store = VectorStoreService()
rag = RagSummarizeService(vector_store)

@tool(description="从向量知识库中检索课程资料的相关内容")
def rag_summarize(query: str) -> str:
    """从用户上传的课程资料中检索与 query 相关的知识点、概念解释、推导过程等

    Args:
        query: 检索关键词，贴合用户问题的核心概念

    Returns:
        匹配的课程资料内容
    """
    return rag.rag_summarize(query)
