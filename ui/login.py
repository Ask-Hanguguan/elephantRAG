"""
登录页面
================================================
纯 Streamlit 原生组件，无自定义 CSS
"""
import streamlit as st

from auth.models import get_user_by_username, init_default_users
from auth.password import verify_password
from auth.jwt_handler import create_access_token
from utils.logger_handler import logger


def login_page() -> None:
    """登录页面"""
    init_default_users()

    st.title("🔐 企业文档智能助手")
    st.caption("请登录后使用")

    with st.form("login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")

        if st.form_submit_button("登录", type="primary", use_container_width=True):
            if not username or not password:
                st.error("请输入用户名和密码")
                return

            user = get_user_by_username(username)
            if user is None or not verify_password(password, user.password_hash):
                st.error("用户名或密码错误")
                return

            if not user.is_active:
                st.error("用户已禁用，请联系管理员")
                return

            st.session_state["user"] = user
            st.session_state["access_token"] = create_access_token(
                user.user_id, user.username, user.role, user.tenant_id
            )
            logger.info(f"[web] 用户登录: {username}")
            st.rerun()
