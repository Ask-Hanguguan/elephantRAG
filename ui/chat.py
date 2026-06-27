"""
智能问答页面
================================================
通过 ApiClient 与 FastAPI 后端通信，SSE 流式展示对话。

防抖动策略：
- CSS 始终注入（不因 active/welcome 切换变化），避免布局跳变
- ``st.chat_input`` 始终在底部调用，位置稳定
- 消息用 ``st.chat_message`` 逐一渲染，容器复用 Streamlit 内部 key
"""
import streamlit as st

from ui.api_client import ApiClient
from ui.styles import inject_global_css


CHAT_CSS = """
<style>
/* 输入栏固定在视口底部 */
[data-testid="stChatInput"] {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: #F5F7FB;
    padding: 12px 24px 20px 24px;
    z-index: 100;
}
@media (min-width: 576px) {
    [data-testid="stChatInput"] { left: 336px; }
}

/* 主内容底部留空给固定输入栏 */
.stMainBlockContainer .block-container {
    padding-bottom: 100px;
}

/* ── 欢迎屏 ── */
.welcome-center {
    text-align: center;
    margin-top: 20vh;
}
.welcome-center .welcome-icon { font-size: 4rem; }
.welcome-center h2 {
    font-size: 1.5rem; font-weight: 700; color: #1A202C; margin-bottom: 0.3rem;
}
.welcome-center p { color: #888; font-size: 1rem; }
</style>
"""


def _has_messages() -> bool:
    return len(st.session_state.get("messages", [])) > 0


def _handle_stream(client: ApiClient, prompt: str):
    """SSE 流式生成 AI 回复"""
    kb_name = st.session_state.get("chat_kb", "default")
    session_id = st.session_state.get("session_id")

    full = ""
    new_sid = None
    placeholder = st.empty()

    try:
        for event_type, data in client.chat_stream(prompt, kb_name, session_id):
            if event_type == "token":
                full += data["token"]
                placeholder.markdown(full + "▌")
            elif event_type == "metadata":
                new_sid = data["metadata"]["session_id"]
            elif event_type == "error":
                placeholder.error(data.get("error", "未知错误"))
                return

        placeholder.markdown(full)
        if new_sid:
            st.session_state["session_id"] = new_sid

    except Exception as e:
        placeholder.error(f"请求失败: {e}")
        full = f"抱歉，请求失败: {str(e)}"

    st.session_state["messages"].append({"role": "assistant", "content": full})


def chat_page() -> None:
    """智能问答主页面"""
    client = ApiClient()

    # ── CSS 始终注入（稳定布局） ──
    inject_global_css()
    st.markdown(CHAT_CSS, unsafe_allow_html=True)

    has_msgs = _has_messages()

    # ── 头部 ──
    if has_msgs:
        st.title("📄 知识库智能助手")
        st.caption("基于 RAG + Agent 的企业文档智能问答")
    else:
        st.markdown("""
        <div class="welcome-center">
            <div class="welcome-icon">🐘</div>
            <h2>ElephantRAG</h2>
            <p>上传文档到知识库，然后向我提问</p>
        </div>
        """, unsafe_allow_html=True)

    # ── 消息历史 ──
    for message in st.session_state.get("messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # ── 输入框（始终在最后，位置固定） ──
    prompt = st.chat_input("输入你的查询问题...")
    if not prompt:
        return

    # ── 发送 ──
    # 记录用户消息
    st.session_state["messages"].append({"role": "user", "content": prompt})

    # 流式 AI 回复
    with st.chat_message("assistant"):
        _handle_stream(client, prompt)

    st.rerun()
