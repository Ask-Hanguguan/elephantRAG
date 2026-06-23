"""
模型 Provider 抽象层
================================================
将 LLM 和 Embedding 的创建逻辑从 factory.py 解耦,
支持多提供商切换(DashScope 云 API / Ollama 本地模型),
满足企业私有化部署需求。
"""
from abc import ABC, abstractmethod
from typing import Optional

from langchain_community.chat_models.tongyi import ChatTongyi, BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.embeddings import Embeddings

from utils.config_handler import rag_conf
from utils.logger_handler import logger


# ============================================================
# 抽象接口
# ============================================================
class LLMProvider(ABC):
    """LLM 对话模型提供商抽象接口"""

    @abstractmethod
    def create_llm(self) -> BaseChatModel:
        """创建并返回 LLM 实例"""
        pass


class EmbeddingProvider(ABC):
    """Embedding 嵌入模型提供商抽象接口"""

    @abstractmethod
    def create_embedding(self) -> Embeddings:
        """创建并返回 Embedding 实例"""
        pass


# ============================================================
# DashScope 提供商(通义千问云 API)
# ============================================================
class DashScopeLLMProvider(LLMProvider):
    """DashScope 通义千问对话模型"""

    def create_llm(self) -> BaseChatModel:
        logger.info(f"[provider] 创建 DashScope LLM: {rag_conf['chat_model_name']}")
        return ChatTongyi(model=rag_conf["chat_model_name"])


class DashScopeEmbeddingProvider(EmbeddingProvider):
    """DashScope 通义千问嵌入模型"""

    def create_embedding(self) -> Embeddings:
        logger.info(f"[provider] 创建 DashScope Embedding: {rag_conf['embedding_model_name']}")
        return DashScopeEmbeddings(model=rag_conf["embedding_model_name"])


# ============================================================
# Ollama 提供商(本地模型,私有化部署)
# ============================================================
class OllamaLLMProvider(LLMProvider):
    """Ollama 本地对话模型,适用于私有化内网部署"""

    def create_llm(self) -> BaseChatModel:
        # 延迟导入,避免未安装 ollama 包时启动失败
        from langchain_community.chat_models import ChatOllama

        ollama_conf = rag_conf.get("ollama", {})
        base_url = ollama_conf.get("base_url", "http://localhost:11434")
        model_name = ollama_conf.get("chat_model_name", "qwen2.5:7b")
        logger.info(f"[provider] 创建 Ollama LLM: {model_name} @ {base_url}")
        return ChatOllama(base_url=base_url, model=model_name)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama 本地嵌入模型"""

    def create_embedding(self) -> Embeddings:
        from langchain_community.embeddings import OllamaEmbeddings

        ollama_conf = rag_conf.get("ollama", {})
        base_url = ollama_conf.get("base_url", "http://localhost:11434")
        model_name = ollama_conf.get("embedding_model_name", "nomic-embed-text")
        logger.info(f"[provider] 创建 Ollama Embedding: {model_name} @ {base_url}")
        return OllamaEmbeddings(base_url=base_url, model=model_name)


# ============================================================
# Provider 工厂
# ============================================================
_PROVIDER_MAP = {
    "dashscope": {
        "llm": DashScopeLLMProvider,
        "embedding": DashScopeEmbeddingProvider,
    },
    "ollama": {
        "llm": OllamaLLMProvider,
        "embedding": OllamaEmbeddingProvider,
    },
}


def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    根据 config/rag.yaml 中的 provider 配置返回 LLM 提供商实例

    :param provider_name: 提供商名称,为空则从配置读取
    :return: LLMProvider 实例
    """
    name = provider_name or rag_conf.get("provider", "dashscope")
    if name not in _PROVIDER_MAP:
        logger.warning(f"[provider] 未知提供商 '{name}',回退到 dashscope")
        name = "dashscope"
    return _PROVIDER_MAP[name]["llm"]()


def get_embedding_provider(provider_name: Optional[str] = None) -> EmbeddingProvider:
    """
    根据 config/rag.yaml 中的 provider 配置返回 Embedding 提供商实例

    :param provider_name: 提供商名称,为空则从配置读取
    :return: EmbeddingProvider 实例
    """
    name = provider_name or rag_conf.get("provider", "dashscope")
    if name not in _PROVIDER_MAP:
        logger.warning(f"[provider] 未知提供商 '{name}',回退到 dashscope")
        name = "dashscope"
    return _PROVIDER_MAP[name]["embedding"]()
