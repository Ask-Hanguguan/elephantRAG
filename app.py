import time

import streamlit as st
from agent.react_agent import ReactAgent

st.title("📚 期末复习助手")
st.caption("上传你的课程资料，轻松复习备考！支持 PDF、PPT、Word 等格式")
st.divider()

if "message" not in st.session_state:
    st.session_state["message"] = [{"role":"assistant","content":"你好，我是期末复习助手！请先上传你要复习的课程资料，然后就可以向我提问啦～"}]

if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

prompt =st.chat_input("输入你的复习问题...")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    response_messages =[]
    with st.spinner("正在查阅资料..."):
        res_stream = st.session_state['agent'].execute_stream(prompt)

        def capture(generator,cache_list):
            for chunk in generator:
                cache_list.append(chunk)

                for char in chunk:
                    time.sleep(0.01)
                    yield char

        st.chat_message("assistant").write_stream(capture(res_stream, response_messages))
        st.session_state["message"].append({"role": "assistant", "content": response_messages[-1]})
        st.rerun()
