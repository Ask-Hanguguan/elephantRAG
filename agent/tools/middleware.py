from typing import Callable

from langchain.agents import AgentState
from langgraph.runtime import Runtime
from langgraph.types import Command
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from core.logger import logger
from core.config import load_prompt


def _load_system_prompt() -> str:
    try:
        return load_prompt("main")
    except Exception:
        return "你是一个企业文档智能助手。"


def _load_report_prompt() -> str:
    try:
        return load_prompt("report")
    except Exception:
        return "请生成一份详细的报告。"


@wrap_tool_call
def monitor_tool(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    logger.info(f"[tool monitor]执行工具: {request.tool_call['name']}")
    logger.info(f"[tool monitor]参数: {request.tool_call['args']}")
    try:
        result = handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")
        return result

    except Exception as e:
        logger.info(f"工具{request.tool_call['name']}调用失败: {e}")
        raise e


@before_model
def log_before_model(state: AgentState, runtime: Runtime):
    logger.info(f"[log_before_model]: 即将调用模型，带有{len(state['messages'])}条消息")
    logger.info(f"[log_before_model][{type(state['messages'][-1]).__name__}]: {state['messages'][-1].content.strip()[:100]}")

    return None


@dynamic_prompt
def report_prompt_switch(request: ModelRequest) -> str:
    is_report = request.runtime.context.get("report", False)
    if is_report:
        return _load_report_prompt()

    return _load_system_prompt()
