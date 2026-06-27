"""
会话状态初始化
================================================
管理 Streamlit 前端状态。

两个独立的知识库选择：
- ``chat_kb`` — 侧边栏选择，控制 RAG 对话检索的知识库
- ``manage_kb`` — 知识库管理页面选择，控制文档操作的知识库
"""
import streamlit as st


def init_session_state() -> None:
    """初始化 Streamlit session_state"""
    if "chat_kb" not in st.session_state:
        st.session_state["chat_kb"] = "default"
    if "manage_kb" not in st.session_state:
        st.session_state["manage_kb"] = "default"
    if "kb_list" not in st.session_state:
        st.session_state["kb_list"] = []
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = None
    if "session_list" not in st.session_state:
        st.session_state["session_list"] = []
    # 侧边栏数据是否需要刷新
    if "sidebar_dirty" not in st.session_state:
        st.session_state["sidebar_dirty"] = True
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "api_ready" not in st.session_state:
        st.session_state["api_ready"] = False
