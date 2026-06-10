from abc import ABC,abstractmethod
from langchain_community.chat_models.tongyi import ChatTongyi,BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.embeddings import Embeddings
from typing import Optional
from utils.config_handler import rag_conf

class BaseChatModelFactory(ABC):
    @abstractmethod     # 强制子类必须实现某些方法
    def generator(self)->Optional[BaseChatModel | Embeddings]:
        pass

class ChatModelFactory(BaseChatModelFactory):
    def generator(self)->Optional[BaseChatModel | Embeddings]:
        return ChatTongyi(model=rag_conf["chat_model_name"])

class EmbeddingsFactory(BaseChatModelFactory):
    def generator(self)->Optional[BaseChatModel | Embeddings]:
        return DashScopeEmbeddings(model=rag_conf["embedding_model_name"])

chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()

'''
你需要根据不同条件创建不同对象？
└─ 是 → 创建逻辑在多处重复？
    └─ 是 → 用工厂模式
    └─ 否 → 写个函数就行
'''