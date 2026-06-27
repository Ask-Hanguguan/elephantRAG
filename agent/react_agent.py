"""
ReAct Agent — LLM + 工具调度核心

支持传入对话历史，通过 KBManager 获取当前知识库上下文。
"""

from typing import Optional

from langchain.agents import create_agent
from agent.tools.agent_tools import kb_retrieve, kb_list_docs
from model.factory import chat_model
from core.config import load_prompt


class ReactAgent(object):
    def __init__(self):
        system_prompt = self._load_system_prompt()
        self.agent = create_agent(
            model=chat_model,
            system_prompt=system_prompt,
            tools=[kb_retrieve, kb_list_docs],
        )

    def _load_system_prompt(self) -> str:
        """加载 system prompt，失败时使用默认提示"""
        try:
            return load_prompt("main")
        except (FileNotFoundError, ValueError, KeyError):
            return "你是一个企业文档智能助手，请基于知识库中的文档内容回答用户问题。"

    def execute_stream(self, query: str, history: Optional[list] = None):
        """流式执行 agent

        Args:
            query: 用户当前问题
            history: 历史消息列表 [{"role": "user"/"assistant", "content": "..."}, ...]
        """
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # 添加当前用户输入
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}

        for chunk in self.agent.stream(input_dict, stream_mode='values'):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"
