"""
会话状态初始化
================================================
"""
import streamlit as st


def init_session_state() -> None:
    """初始化 Streamlit session_state"""
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "access_token" not in st.session_state:
        st.session_state["access_token"] = None
    if "message" not in st.session_state:
        st.session_state["message"] = [
            {
                "role": "assistant",
                "content": "你好，我是企业文档智能助手！请先上传需要检索的企业文档，然后就可以向我提问啦～",
            }
        ]
