"""
企业文档智能助手 — Streamlit 主入口
================================================
"""
import streamlit as st

from agent.react_agent import ReactAgent
from ui.session import init_session_state
from ui.login import login_page
from ui.chat import chat_page
from ui.documents import documents_page
from ui.sidebar import sidebar


def main() -> None:
    """主入口"""
    st.set_page_config(
        page_title="企业文档智能助手",
        page_icon="📄",
        layout="centered",
        initial_sidebar_state="expanded",
    )

    init_session_state()

    # 未登录 → 登录页
    if st.session_state.get("user") is None:
        login_page()
        return

    # 延迟加载 agent（避免未登录时加载模型）
    if "agent" not in st.session_state:
        with st.spinner("正在加载模型..."):
            st.session_state["agent"] = ReactAgent()

    sidebar()

    tab_chat, tab_docs = st.tabs(["💬 智能问答", "📁 文档管理"])
    with tab_chat:
        chat_page()
    with tab_docs:
        documents_page()


if __name__ == "__main__":
    main()
