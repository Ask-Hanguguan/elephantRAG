import os
import time
import threading

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


# ============================================================
# 登录页面
# ============================================================
def login_page():
    """登录页面"""
    init_default_users()

    # 卡片容器（使用 HTML + st.markdown）
    st.markdown('<div class="login-card">', unsafe_allow_html=True)

    st.markdown('<h1 style="text-align:center; margin-bottom:4px;">🔐 企业文档智能助手</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align:center; color:#6b7280; margin-bottom:24px;">请登录后使用</p>', unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名", label_visibility="collapsed")
        password = st.text_input("密码", type="password", placeholder="请输入密码", label_visibility="collapsed")

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

    st.markdown('</div>', unsafe_allow_html=True)


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

    # ---- 检查后台入库结果 ----
    _check_ingest_result()

    # ---- 后台入库状态条 ----
    t_running = st.session_state.get("_ingest_thread")
    if t_running and t_running.is_alive():
        fname = st.session_state.get("_ingest_file", "")
        st.info(f"⏳ 正在后台入库: {fname}，可切换页面，入库不会中断")
        time.sleep(2)
        st.rerun()

    # ---- 文档上传 ----
    if can_manage:
        st.subheader("上传文档")
        allowed_exts = chroma_conf["allow_knowledge_file_type"]
        uploaded_file = st.file_uploader(
            f"选择文件(支持: {', '.join(allowed_exts)})",
            type=allowed_exts,
        )

        if uploaded_file is not None:
            data_path = get_abs_path(chroma_conf["data_path"])
            os.makedirs(data_path, exist_ok=True)
            file_path = os.path.join(data_path, uploaded_file.name)

            # 先写磁盘
            try:
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            except Exception as e:
                st.error(f"文件保存失败: {str(e)}")
                return

            # 入库按钮
            col_btn, col_hint = st.columns([1, 3])
            with col_btn:
                if st.button("入库", type="primary"):
                    _start_ingest_thread(file_path, uploaded_file.name)
            with col_hint:
                st.caption("入库在后台运行，可切换页面、继续提问")
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

    # 获取已入库记录
    from agent.tools.agent_tools import vector_store
    md5_records = vector_store.md5_store.get_all_records()

    # 检查是否有正在入库的文件
    current_ingest = st.session_state.get("_ingest_file", "")
    current_thread = st.session_state.get("_ingest_thread")

    for fname in files:
        fpath = os.path.join(data_path, fname)
        size_kb = os.path.getsize(fpath) / 1024

        # 判断状态
        is_ingested = fpath in md5_records
        is_processing = (
            current_thread and current_thread.is_alive() and fname == current_ingest
        )

        if is_ingested:
            status_icon = "✅"
            status_text = "已入库"
        elif is_processing:
            status_icon = "⏳"
            status_text = "入库中"
        else:
            status_icon = "🔴"
            status_text = "待入库"

        col1, col2, col3, col4 = st.columns([5, 2, 2, 2])
        with col1:
            st.write(f"📄 {fname}")
        with col2:
            st.write(f"{size_kb:.1f} KB")
        with col3:
            st.write(f"{status_icon} {status_text}")
        with col4:
            if can_manage:
                if is_ingested:
                    if st.button("删除", key=f"del_{fname}"):
                        try:
                            os.remove(fpath)
                            vector_store.load_document()
                            st.success(f"已删除: {fname}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败: {str(e)}")
                elif not is_processing:
                    if st.button("入库", key=f"ingest_{fname}"):
                        _start_ingest_thread(fpath, fname)
                        st.rerun()


def _check_ingest_result():
    """检查后台入库结果，显示完成/失败消息"""
    result = st.session_state.pop("_ingest_result", None)
    if result is None:
        return
    if result["ok"]:
        st.success(f"✅ {result['name']} 入库完成！")
        time.sleep(1)
        st.rerun()
    else:
        st.error(f"❌ {result['name']} 入库失败: {result['error']}")
        time.sleep(2)


def _start_ingest_thread(file_path, file_name):
    """启动后台入库线程"""
    current = st.session_state.get("_ingest_thread")
    if current and current.is_alive():
        st.warning(f"已有文件正在入库 ({st.session_state.get('_ingest_file', '')})，请等待完成")
        return

    logger.info(f"[后台入库] 启动: {file_name}")

    def _run():
        try:
            from agent.tools.agent_tools import vector_store
            vector_store.load_single_document(file_path)
            st.session_state["_ingest_result"] = {"ok": True, "name": file_name}
            logger.info(f"[后台入库] 完成: {file_name}")
        except Exception as e:
            st.session_state["_ingest_result"] = {
                "ok": False, "name": file_name, "error": str(e)
            }
            logger.error(f"[后台入库] 失败: {file_name} - {str(e)}", exc_info=True)

    t = threading.Thread(target=_run, daemon=True)
    st.session_state["_ingest_thread"] = t
    st.session_state["_ingest_file"] = file_name
    t.start()
    st.info(f"⏳ 已启动后台入库: {file_name}，可切换页面")
    time.sleep(0.5)
    st.rerun()


# ============================================================
# 侧边栏
# ============================================================
def sidebar():
    """侧边栏:用户信息和登出"""
    user = st.session_state["user"]
    with st.sidebar:
        # 用户头像（取用户名首字母）
        avatar_letter = user.username[0].upper() if user.username else "U"
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
            <div style="width:40px; height:40px; border-radius:50%; background:#1a73e8;
                        display:flex; align-items:center; justify-content:center;
                        color:white; font-weight:600; font-size:16px;">
                {avatar_letter}
            </div>
            <div>
                <div style="font-weight:600; font-size:1rem; color:#1f2937;">{user.username}</div>
                <span style="font-size:0.75rem; background:#e8f0fe; color:#1a73e8;
                           padding:2px 8px; border-radius:12px; font-weight:500;">
                    {user.role}
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()
        if st.button("🚪 登出", use_container_width=True, type="secondary"):
            logger.info(f"[web] 用户登出: {user.username}")
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# ============================================================
# 全局 CSS 注入
# ============================================================
def inject_css():
    """注入全局自定义样式"""
    st.markdown("""
    <style>
    .stApp {
        background-color: #f5f7fa;
    }
    .main .block-container {
        max-width: 1000px;
        padding-top: 1rem;
    }
    div[data-testid="stTabs"] {
        position: sticky !important;
        top: 0;
        z-index: 999;
        background: #ffffff;
        padding: 0.5rem 0 0 0;
        margin-bottom: 1rem;
    }
    div[data-testid="stTabs"] > div {
        background: transparent;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border-radius: 8px;
        padding: 0.25rem 0.5rem;
    }
    div[data-testid="stTabs"] button {
        font-size: 0.95rem;
        font-weight: 500;
        padding: 0.5rem 1.2rem;
        transition: color 0.2s;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #1a73e8 !important;
        font-weight: 600;
    }
    .stChatMessage:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #1a73e8;
        color: white;
        border-radius: 18px 18px 4px 18px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .stChatMessage:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-left: 4px solid #1a73e8;
        border-radius: 18px 18px 18px 4px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .stChatMessage p {
        margin: 0;
        line-height: 1.6;
    }
    .stChatMessage:has([data-testid="stChatMessageAvatarUser"]) p {
        color: white;
    }
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e5e7eb;
    }
    section[data-testid="stSidebar"] .stButton button {
        border-radius: 8px;
        transition: all 0.2s;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        background-color: #f3f4f6;
        border-color: #d1d5db;
    }
    div[data-testid="stVerticalBlock"]:has(> div > div > .login-card) {
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 80vh;
    }
    .login-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 2.5rem;
        box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        max-width: 400px;
        width: 100%;
        margin: 0 auto;
    }
    .login-card h1 {
        text-align: center;
        font-size: 1.5rem;
        margin-bottom: 0.25rem;
        color: #1f2937;
    }
    .login-card .caption {
        text-align: center;
        color: #6b7280;
        font-size: 0.875rem;
        margin-bottom: 1.5rem;
    }
    div[data-testid="stFileUploader"] {
        border: 2px dashed #d1d5db;
        border-radius: 12px;
        padding: 1rem;
        background: #fafafa;
    }
    .stAlert {
        border-radius: 10px;
        border-left: 4px solid #1a73e8;
    }
    .stButton button {
        border-radius: 8px;
        font-weight: 500;
    }
    button[data-testid="baseButton-primary"] {
        background-color: #1a73e8;
        border-color: #1a73e8;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #1557b0 !important;
        border-color: #1557b0 !important;
    }
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: transparent;
    }
    ::-webkit-scrollbar-thumb {
        background: #c4c4c4;
        border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #a0a0a0;
    }
    </style>
    """, unsafe_allow_html=True)


# ============================================================
# 主入口
# ============================================================
def main():
    """主入口"""
    st.set_page_config(
        page_title="企业文档智能助手",
        page_icon="📄",
        layout="centered",
        initial_sidebar_state="expanded",
    )

    inject_css()

    init_session_state()

    # 未登录 → 登录页
    if st.session_state.get("user") is None:
        login_page()
        return

    # 初始化 agent（延迟加载，避免未登录时加载模型）
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

