"""
企业文档智能助手 - Streamlit Web 应用
================================================
提供登录认证、智能问答、文档管理功能

启动方式:
    streamlit run app.py
"""
import os
import time

import streamlit as st

from agent.react_agent import ReactAgent
from auth.models import get_user_by_username, init_default_users
from auth.password import verify_password
from auth.jwt_handler import create_access_token
from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


# ============================================================
# Session State 初始化
# ============================================================
def init_session_state():
    """初始化 Streamlit session_state"""
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "access_token" not in st.session_state:
        st.session_state["access_token"] = None
    if "message" not in st.session_state:
        st.session_state["message"] = [
            {"role": "assistant", "content": "你好，我是企业文档智能助手！请先上传需要检索的企业文档，然后就可以向我提问啦～"}
        ]
    if "agent" not in st.session_state:
        st.session_state["agent"] = None


# ============================================================
# 登录/登出
# ============================================================
def login_page():
    """登录页面"""
    st.title("📄 企业文档智能助手")
    st.caption("请登录后使用")

    with st.form("login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submit = st.form_submit_button("登录")

        if submit:
            if not username or not password:
                st.error("请输入用户名和密码")
                return

            user = get_user_by_username(username)
            if not user or not verify_password(password, user.password_hash):
                st.error("用户名或密码错误")
                return

            if not user.is_active:
                st.error("用户已禁用，请联系管理员")
                return

            # 登录成功，保存状态
            st.session_state["user"] = user
            st.session_state["access_token"] = create_access_token(
                user.user_id, user.username, user.role, user.tenant_id
            )
            st.session_state["agent"] = ReactAgent()
            logger.info(f"[web] 用户登录: {username}")
            st.rerun()


def logout():
    """登出"""
    username = st.session_state.get("user")
    if username:
        logger.info(f"[web] 用户登出: {username.username}")
    st.session_state["user"] = None
    st.session_state["access_token"] = None
    st.session_state["agent"] = None
    st.session_state["message"] = [
        {"role": "assistant", "content": "你好，我是企业文档智能助手！请先上传需要检索的企业文档，然后就可以向我提问啦～"}
    ]
    st.rerun()


# ============================================================
# 问答页面
# ============================================================
def chat_page():
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

        response_messages = []
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
            # 合并所有 chunk 作为完整回答
            full_response = "".join(response_messages) if response_messages else ""
            st.session_state["message"].append(
                {"role": "assistant", "content": full_response}
            )
            st.rerun()


# ============================================================
# 文档管理页面
# ============================================================
def documents_page():
    """文档管理页面"""
    st.title("📁 文档管理")
    st.caption("上传、查看、删除企业知识库文档")
    st.divider()

    user = st.session_state["user"]
    can_manage = user.role in ("admin", "editor")

    # ---- 文档上传 ----
    if can_manage:
        st.subheader("上传文档")
        allowed_exts = chroma_conf["allow_knowledge_file_type"]
        uploaded_file = st.file_uploader(
            f"选择文件(支持: {', '.join(allowed_exts)})",
            type=allowed_exts,
        )

        if uploaded_file is not None:
            if st.button("入库", type="primary"):
                data_path = get_abs_path(chroma_conf["data_path"])
                os.makedirs(data_path, exist_ok=True)
                file_path = os.path.join(data_path, uploaded_file.name)

                try:
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    with st.spinner("正在入库..."):
                        # 复用 vector_store 增量入库
                        from agent.tools.agent_tools import vector_store
                        vector_store.load_document()

                    st.success(f"文档 '{uploaded_file.name}' 已成功入库！")
                    st.rerun()
                except Exception as e:
                    st.error(f"入库失败: {str(e)}")
    else:
        st.info("您当前角色为 viewer，无文档管理权限。如需上传文档，请联系管理员分配 editor 或 admin 角色。")

    st.divider()

    # ---- 文档列表 ----
    st.subheader("文档列表")
    data_path = get_abs_path(chroma_conf["data_path"])
    allowed_exts = tuple(chroma_conf["allow_knowledge_file_type"])

    if not os.path.isdir(data_path):
        st.warning("数据目录不存在")
        return

    files = sorted([f for f in os.listdir(data_path) if f.endswith(allowed_exts)])

    if not files:
        st.info("暂无文档，请先上传")
        return

    for fname in files:
        fpath = os.path.join(data_path, fname)
        size_kb = os.path.getsize(fpath) / 1024
        col1, col2, col3 = st.columns([6, 2, 2])
        with col1:
            st.write(f"📄 {fname}")
        with col2:
            st.write(f"{size_kb:.1f} KB")
        with col3:
            if can_manage:
                if st.button("删除", key=f"del_{fname}"):
                    try:
                        os.remove(fpath)
                        from agent.tools.agent_tools import vector_store
                        vector_store.load_document()
                        st.success(f"已删除: {fname}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除失败: {str(e)}")


# ============================================================
# 侧边栏
# ============================================================
def sidebar():
    """侧边栏:用户信息和登出"""
    user = st.session_state["user"]
    with st.sidebar:
        st.write("### 用户信息")
        st.write(f"**用户名:** {user.username}")
        st.write(f"**角色:** {user.role}")
        st.write(f"**租户:** {user.tenant_id}")
        st.divider()
        if st.button("退出登录"):
            logout()


# ============================================================
# 主入口
# ============================================================
def main():
    init_session_state()

    # 首次启动初始化默认用户
    init_default_users()

    user = st.session_state["user"]

    if user is None:
        # 未登录显示登录页
        login_page()
    else:
        # 已登录显示主界面
        sidebar()

        # 功能标签页
        tab_chat, tab_docs = st.tabs(["💬 智能问答", "📁 文档管理"])
        with tab_chat:
            chat_page()
        with tab_docs:
            documents_page()


if __name__ == "__main__":
    main()
