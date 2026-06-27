"""
Agent 工具集 — 通过 KBManager 获取当前知识库的服务实例

不再持有全局 VectorStoreService 单例，改为运行时从 KBManager 动态获取。
"""

import os
from typing import Optional

from langchain_core.tools import tool
from core.config import agent_conf
from core.logger import logger
from kb.manager import init_kb_manager


def _get_kb():
    """获取 KBManager 单例（始终调用 init 获取最新实例）"""
    return init_kb_manager()


def _get_current_rag():
    """获取当前知识库的 RagSummarizeService（延迟初始化）"""
    kb = _get_kb()
    vs = kb.get_vector_store()
    from kb.rag_service import RagSummarizeService
    return RagSummarizeService(vs)


@tool(description="从当前知识库中检索与用户问题相关的文档内容")
def kb_retrieve(query: str) -> str:
    """从当前知识库中检索与 query 相关的文档内容

    Args:
        query: 检索关键词，贴合用户问题的核心概念

    Returns:
        匹配的文档内容（含来源标注）
    """
    try:
        rag = _get_current_rag()
        result = rag.rag_summarize(query)
        return result
    except Exception as e:
        logger.error(f"[Agent Tool] kb_retrieve 失败: {e}", exc_info=True)
        return f"知识库检索失败: {str(e)}"


@tool(description="列出当前知识库中的所有文档")
def kb_list_docs() -> str:
    """列出当前知识库中的所有文档名称和状态"""
    try:
        kb = _get_kb()
        docs = kb.list_documents()
        if not docs:
            return "当前知识库中没有文档。"

        lines = ["当前知识库文档列表："]
        for d in docs:
            lines.append(f"- {d['file_name']} ({d['status']}, {d.get('chunk_count', 0)} chunks)")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[Agent Tool] kb_list_docs 失败: {e}", exc_info=True)
        return f"获取文档列表失败: {str(e)}"
