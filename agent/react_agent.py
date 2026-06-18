from langchain.agents import create_agent
from agent.tools.agent_tools import rag_summarize
from model.factory import chat_model
from utils.prompt_loader import load_system_prompt


class ReactAgent(object):
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompt(),
            tools=[rag_summarize],
        )

    # 流式执行 agent
    def execute_stream(self, query):
        input_dict = {
            "messages": [
                {"role": "user", "content": query}
            ]
        }

        for chunk in self.agent.stream(input_dict, stream_mode='values'):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"

if __name__ == '__main__':
    agent = ReactAgent()
    for chunk in agent.execute_stream("什么是决策树？"):
        print(chunk, end="", flush=True)
