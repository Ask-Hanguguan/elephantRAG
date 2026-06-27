"""
模型 Provider 抽象层
================================================
将 LLM 和 Embedding 的创建逻辑从 factory.py 解耦,
支持多提供商切换(DashScope 云 API / Ollama 本地模型 / OpenAI 兼容接口).

增强:LLM 和 Embedding 可独立配置不同提供商。
"""
from abc import ABC, abstractmethod
from typing import Optional

from core.config import rag_conf
from core.logger import logger


# ============================================================
# 抽象接口
# ============================================================
class LLMProvider(ABC):
    """LLM 对话模型提供商抽象接口"""

    @abstractmethod
    def create_llm(self):
        """创建并返回 LLM 实例"""
        pass


class EmbeddingProvider(ABC):
    """Embedding 嵌入模型提供商抽象接口"""

    @abstractmethod
    def create_embedding(self):
        """创建并返回 Embedding 实例"""
        pass


# ============================================================
# 配置读取辅助
# ============================================================

def _get_llm_config():
    """获取 LLM 配置块（兼容新旧格式）"""
    llm_cfg = rag_conf.get("llm")
    if llm_cfg:
        return llm_cfg
    # 向后兼容：旧格式 flat 配置
    return {
        "provider": rag_conf.get("provider", "dashscope"),
        "chat_model_name": rag_conf.get("chat_model_name", "qwen-max"),
    }


def _get_embedding_config():
    """获取 Embedding 配置块（兼容新旧格式）"""
    emb_cfg = rag_conf.get("embedding")
    if emb_cfg:
        return emb_cfg
    # 向后兼容：旧格式 flat 配置
    return {
        "provider": rag_conf.get("provider", "dashscope"),
        "embedding_model_name": rag_conf.get("embedding_model_name", "text-embedding-async-v1"),
    }


def _get_provider_name(config: dict, default: str) -> str:
    return config.get("provider", default)


# ============================================================
# DashScope 提供商(通义千问云 API)
# ============================================================

class DashScopeLLMProvider(LLMProvider):
    """DashScope 通义千问对话模型"""

    def create_llm(self):
        from langchain_community.chat_models.tongyi import ChatTongyi
        from langchain_community.chat_models.tongyi import BaseChatModel

        cfg = _get_llm_config()
        model_name = cfg.get("dashscope", {}).get("model_name") or cfg.get("chat_model_name", "qwen-max")
        logger.info(f"[provider] 创建 DashScope LLM: {model_name}")
        return ChatTongyi(model=model_name)


class DashScopeEmbeddingProvider(EmbeddingProvider):
    """DashScope 通义千问嵌入模型"""

    def create_embedding(self):
        from langchain_community.embeddings import DashScopeEmbeddings

        cfg = _get_embedding_config()
        model_name = cfg.get("dashscope", {}).get("model_name") or cfg.get("embedding_model_name", "text-embedding-async-v1")
        logger.info(f"[provider] 创建 DashScope Embedding: {model_name}")
        return DashScopeEmbeddings(model=model_name)


# ============================================================
# Ollama 提供商(本地模型,私有化部署)
# ============================================================

class OllamaLLMProvider(LLMProvider):
    """Ollama 本地对话模型"""

    def create_llm(self):
        from langchain_community.chat_models import ChatOllama
        from langchain_community.chat_models.tongyi import BaseChatModel

        cfg = _get_llm_config()
        ollama_cfg = cfg.get("ollama", {})
        base_url = ollama_cfg.get("base_url", "http://localhost:11434")
        model_name = ollama_cfg.get("model_name", "qwen2.5:7b")
        logger.info(f"[provider] 创建 Ollama LLM: {model_name} @ {base_url}")
        return ChatOllama(base_url=base_url, model=model_name)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama 本地嵌入模型"""

    def create_embedding(self):
        from langchain_community.embeddings import OllamaEmbeddings

        cfg = _get_embedding_config()
        ollama_cfg = cfg.get("ollama", {})
        base_url = ollama_cfg.get("base_url", "http://localhost:11434")
        model_name = ollama_cfg.get("model_name", "nomic-embed-text")
        logger.info(f"[provider] 创建 Ollama Embedding: {model_name} @ {base_url}")
        return OllamaEmbeddings(base_url=base_url, model=model_name)


# ============================================================
# OpenAI 兼容提供商
# ============================================================

class OpenAILLMProvider(LLMProvider):
    """OpenAI 兼容 API 对话模型"""

    def create_llm(self):
        from langchain_openai import ChatOpenAI
        from langchain_community.chat_models.tongyi import BaseChatModel

        cfg = _get_llm_config()
        openai_cfg = cfg.get("openai", {})
        base_url = openai_cfg.get("base_url", "https://api.openai.com/v1")
        model_name = openai_cfg.get("model_name", "gpt-4o")
        logger.info(f"[provider] 创建 OpenAI LLM: {model_name} @ {base_url}")
        return ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=openai_cfg.get("api_key"),
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容嵌入接口"""

    def create_embedding(self):
        from langchain_openai import OpenAIEmbeddings

        cfg = _get_embedding_config()
        openai_cfg = cfg.get("openai", {})
        base_url = openai_cfg.get("base_url", "https://api.openai.com/v1")
        model_name = openai_cfg.get("model_name", "text-embedding-3-small")
        logger.info(f"[provider] 创建 OpenAI Embedding: {model_name} @ {base_url}")
        return OpenAIEmbeddings(
            model=model_name,
            base_url=base_url,
            api_key=openai_cfg.get("api_key"),
        )


# ============================================================
# Provider 注册表
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
    "openai": {
        "llm": OpenAILLMProvider,
        "embedding": OpenAIEmbeddingProvider,
    },
}


def get_llm_provider(provider_name: Optional[str] = None):
    """
    根据配置返回 LLM 提供商实例
    LLM 和 Embedding 可独立配置不同提供商。
    """
    if provider_name:
        name = provider_name
    else:
        cfg = _get_llm_config()
        name = cfg.get("provider", "dashscope")

    if name not in _PROVIDER_MAP:
        logger.warning(f"[provider] 未知 LLM 提供商 '{name}', 回退到 dashscope")
        name = "dashscope"
    return _PROVIDER_MAP[name]["llm"]()


def get_embedding_provider(provider_name: Optional[str] = None):
    """
    根据配置返回 Embedding 提供商实例
    """
    if provider_name:
        name = provider_name
    else:
        cfg = _get_embedding_config()
        name = cfg.get("provider", "dashscope")

    if name not in _PROVIDER_MAP:
        logger.warning(f"[provider] 未知 Embedding 提供商 '{name}', 回退到 dashscope")
        name = "dashscope"
    return _PROVIDER_MAP[name]["embedding"]()
