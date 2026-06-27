"""
知识库智能助手 — Streamlit 主入口
================================================
无认证，通过 ApiClient 与 FastAPI 后端通信。
"""
import streamlit as st

from ui.session import init_session_state
from ui.chat import chat_page
from ui.knowledge import knowledge_page
from ui.sidebar import sidebar
from ui.styles import inject_global_css


def main() -> None:
    """主入口"""
    st.set_page_config(
        page_title="ElephantRAG - 知识库智能助手",
        page_icon="🐘",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()

    # 全局 CSS（仅注入一次）
    inject_global_css()

    # 侧边栏（知识库选择器 + 会话列表）
    sidebar()

    # 主区域 Tab
    tab_chat, tab_docs = st.tabs(["💬 智能问答", "📁 知识库管理"])
    with tab_chat:
        chat_page()
    with tab_docs:
        knowledge_page()


if __name__ == "__main__":
    main()
