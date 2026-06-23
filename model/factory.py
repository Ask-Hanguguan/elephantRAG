"""
模型工厂
================================================
通过 Provider 抽象层创建 LLM 和 Embedding 实例,
支持根据 config/rag.yaml 的 provider 配置切换:
  - dashscope: 通义千问云 API(默认)
  - ollama: 本地模型私有化部署

向后兼容:保留模块级单例 chat_model / embed_model
新代码建议使用工厂函数 get_chat_model() / get_embed_model()
"""
from typing import Optional

from langchain_community.chat_models.tongyi import BaseChatModel
from langchain_core.embeddings import Embeddings

from model.provider import get_llm_provider, get_embedding_provider


def get_chat_model() -> BaseChatModel:
    """
    工厂函数:根据配置创建 LLM 实例

    :return: BaseChatModel 实例
    """
    return get_llm_provider().create_llm()


def get_embed_model() -> Embeddings:
    """
    工厂函数:根据配置创建 Embedding 实例

    :return: Embeddings 实例
    """
    return get_embedding_provider().create_embedding()


# ============================================================
# 向后兼容:模块级单例
# 现有代码 `from model.factory import chat_model` 仍可使用
# 新代码建议使用 get_chat_model() / get_embed_model() 工厂函数
# ============================================================
chat_model: Optional[BaseChatModel] = get_chat_model()
embed_model: Optional[Embeddings] = get_embed_model()
