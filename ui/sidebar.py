"""
侧边栏
================================================
纯 Streamlit 原生组件，无自定义 CSS
"""
import streamlit as st

from utils.logger_handler import logger


def sidebar() -> None:
    """侧边栏：用户信息和登出"""
    user = st.session_state["user"]
    with st.sidebar:
        st.subheader(f"👤 {user.username}")
        st.caption(f"角色: {user.role}")
        st.divider()
        if st.button("🚪 登出", use_container_width=True, type="secondary"):
            logger.info(f"[web] 用户登出: {user.username}")
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
