"""
RAG 摘要服务 — 检索 + LLM 总结

从 rag/rag_service.py 迁移, 移除 segment 依赖, 调整导入路径。
"""

import os

from core.config import chroma_conf, load_prompt
from core.logger import logger
from model.factory import chat_model

RAG_PROMPT_TEMPLATE = """你是一个企业文档智能助手，请根据以下上下文回答问题。

上下文：
{context}

问题：{question}

请基于上下文给出准确、简洁的回答。如果你从上下文中找不到答案，请坦诚告知用户。"""


class RagSummarizeService:
    """RAG 检索增强生成服务"""

    def __init__(self, vector_store):
        self.vector_store = vector_store

    def retriever_docs(self, user_query: str) -> list[dict]:
        """检索相关文档"""
        fusion = self.vector_store.get_fusion_retriever()
        results = fusion.invoke(user_query)
        return results

    def rag_summarize(self, user_query: str) -> str:
        """检索 → 生成完整回答"""
        try:
            docs = self.retriever_docs(user_query)
            context = self._format_context(docs)

            # 日志：输出每条召回 chunk 的摘要
            for i, d in enumerate(docs, 1):
                text = d.get("text", "")
                src = d.get("metadata", {}).get("source", "未知")
                preview = text[:120].replace("\n", " ")
                logger.info(
                    f"[RAG]  召回[{i}/{len(docs)}] "
                    f"score={d.get('score', 0):.3f} "
                    f"src={src.split(chr(92))[-1].split('/')[-1]} "
                    f"=> {preview}{'…' if len(text) > 120 else ''}"
                )

            # 尝试从配置加载 prompt 模板
            try:
                prompt_template = load_prompt("rag")
            except (FileNotFoundError, ValueError, KeyError):
                prompt_template = RAG_PROMPT_TEMPLATE

            prompt = prompt_template.format(
                context=context, question=user_query, input=user_query
            )
            response = chat_model.invoke(prompt)
            return response.content

        except Exception as e:
            logger.error(f"[RAG] 生成回答失败: {e}", exc_info=True)
            return f"抱歉，生成回答时出现错误: {str(e)}"

    def _format_context(self, docs: list[dict]) -> str:
        """将检索结果格式化为上下文文本"""
        if not docs:
            return "（未检索到相关文档内容）"

        parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.get("metadata", {}).get("source", "未知来源")
            text = doc.get("text", "")
            parts.append(f"[来源 {i}] {os.path.basename(source) if 'source' in doc.get('metadata', {}) else '未知'}:\n{text}\n")

        return "\n---\n".join(parts)

    def _get_source_name(self, metadata: dict) -> str:
        """从 metadata 中提取可读的来源文件名"""
        source = metadata.get("source", "")
        if source:
            return os.path.basename(source)
        return metadata.get("title", "未知来源")
