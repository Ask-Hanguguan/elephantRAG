"""
智能问答页面
================================================
"""
import time

import streamlit as st


def chat_page() -> None:
    """智能问答页面"""
    st.title("📄 企业文档智能助手")
    st.caption("上传你的企业文档，轻松检索查询！支持 PDF、PPT、Word、Excel、TXT 等格式")
    st.divider()

    # 显示历史消息
    for message in st.session_state["message"]:
        st.chat_message(message["role"]).write(message["content"])

    # 用户输入
    prompt = st.chat_input("输入你的查询问题...")

    if prompt:
        st.chat_message("user").write(prompt)
        st.session_state["message"].append({"role": "user", "content": prompt})

        response_messages: list[str] = []
        with st.spinner("正在检索企业文档..."):
            res_stream = st.session_state["agent"].execute_stream(prompt)

            def capture(generator, cache_list):
                for chunk in generator:
                    cache_list.append(chunk)
                    for char in chunk:
                        time.sleep(0.01)
                        yield char

            st.chat_message("assistant").write_stream(
                capture(res_stream, response_messages)
            )
            full_response = "".join(response_messages) if response_messages else ""
            st.session_state["message"].append(
                {"role": "assistant", "content": full_response}
            )
            st.rerun()
