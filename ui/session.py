"""
会话状态初始化
================================================
管理 Streamlit 前端状态：知识库选择、对话列表、消息历史。
"""
import streamlit as st


def init_session_state() -> None:
    """初始化 Streamlit session_state"""
    if "kb_name" not in st.session_state:
        st.session_state["kb_name"] = "default"
    if "kb_list" not in st.session_state:
        st.session_state["kb_list"] = []
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = None
    if "session_list" not in st.session_state:
        st.session_state["session_list"] = []
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {
                "role": "assistant",
                "content": "你好，我是知识库智能助手！请先选择或创建一个知识库并上传文档，然后就可以向我提问啦～",
            }
        ]
    if "api_ready" not in st.session_state:
        st.session_state["api_ready"] = False
