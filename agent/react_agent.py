from langchain.agents import create_agent
from agent.tools.agent_tools import (rag_summarize,get_weather,get_user_location,get_user_id,get_current_month,
                                     fetch_external_data,fill_context_for_report)
from model.factory import chat_model
from utils.prompt_loader import load_system_prompt
from agent.tools.middleware import monitor_tool,log_before_model,report_prompt_switch


class ReactAgent(object):
    def __init__(self):
        self.agent = create_agent(
            model = chat_model,
            system_prompt=load_system_prompt(),
            tools=[rag_summarize,get_weather,get_user_location,get_user_id,get_current_month,
                                     fetch_external_data,fill_context_for_report],
            middleware=[monitor_tool,log_before_model,report_prompt_switch]
        )

    #流式执行 agent
    def execute_stream(self,query):
        input_dict = {
            "messages": [
                {"role":"user","content":query}
            ]
        }

        '''
        input_dict：包含用户消息的输入

        stream_mode='values'：返回完整的消息值（而不是只返回 token）
        
        context={"report":False}：这个就是传给 report_prompt_switch 的上下文，让 middleware 知道当前不是报告模式
        '''

        for chunk in self.agent.stream(input_dict,stream_mode='values',context={"report":False}):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"

if __name__ == '__main__':
    agent = ReactAgent()
    for chunk in agent.execute_stream("扫地机器人在我所在地区的气温下如何保养"):
        print(chunk, end="", flush=True)