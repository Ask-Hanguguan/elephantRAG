"""
侧边栏
================================================
知识库切换 + 会话历史。

防抖动策略：
- KB 列表仅首次加载或切 KB 后刷新，不每帧请求
- 会话列表同理，用 ``sidebar_dirty`` 标记控制
- 切换会话时不刷新列表（只更新消息 + session_id）
"""
import streamlit as st

from ui.api_client import ApiClient
from core.logger import logger


def _ensure_sidebar_loaded(client: ApiClient):
    """仅在 dirty 标记或首次时拉取侧边栏数据（避免每 rerun 请求后端）"""
    if st.session_state.get("sidebar_dirty", True):
        try:
            kbs = client.list_knowledge_bases()
            st.session_state["kb_list"] = kbs
        except Exception:
            pass
        try:
            sessions = client.list_sessions()
            st.session_state["session_list"] = sessions
        except Exception:
            pass
        st.session_state["sidebar_dirty"] = False


def _mark_dirty():
    st.session_state["sidebar_dirty"] = True


def _switch_session(session_id: str):
    """切换会话：加载消息，不触发列表刷新"""
    client = ApiClient()
    try:
        resp = client.get_session_messages(session_id)
        msgs = resp.get("messages", [])
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = msgs if msgs else []
    except Exception as e:
        logger.error(f"[Sidebar] 加载会话失败: {e}")
    st.rerun()


def _delete_session(client: ApiClient, session_id: str):
    """删除会话"""
    try:
        client.delete_session(session_id)
        current = st.session_state.get("session_id")
        if current == session_id:
            st.session_state.pop("session_id", None)
            st.session_state["messages"] = []
        _mark_dirty()
        st.rerun()
    except Exception as e:
        st.error(f"删除会话失败: {e}")


def sidebar() -> None:
    """侧边栏：知识库 + 会话"""
    client = ApiClient()
    _ensure_sidebar_loaded(client)

    with st.sidebar:
        st.subheader("🧠 ElephantRAG")

        # ── 知识库选择 ──
        st.markdown("### 📚 检索知识库")
        kbs = st.session_state.get("kb_list", [])
        if kbs:
            current_kb = st.session_state.get("chat_kb", "default")
            if current_kb not in kbs:
                current_kb = kbs[0]
                st.session_state["chat_kb"] = current_kb
            selected = st.selectbox(
                "选择知识库",
                kbs,
                index=kbs.index(current_kb) if current_kb in kbs else 0,
                key="sidebar_kb_selector",
                label_visibility="collapsed",
                help="RAG 对话检索的知识库",
            )
            if selected != current_kb:
                st.session_state["chat_kb"] = selected
                _mark_dirty()
                st.rerun()
        else:
            st.caption("暂无知识库")

        st.divider()

        # ── 会话列表 ──
        st.markdown("### 💬 会话历史")

        if st.button("➕ 新对话", width="stretch", type="primary"):
            kb_name = st.session_state.get("chat_kb", "default")
            new_session = client.create_session(kb_name=kb_name)
            st.session_state["session_id"] = new_session.get("session_id")
            st.session_state["messages"] = []
            _mark_dirty()
            st.rerun()

        sessions = st.session_state.get("session_list", [])
        if sessions:
            current_sid = st.session_state.get("session_id")
            for idx, s in enumerate(sessions[:20]):
                title_full = s.get("title", "新对话")
                sid = s.get("session_id")

                title = title_full[:16] + "…" if len(title_full) > 16 else title_full
                is_active = sid == current_sid

                if is_active:
                    indicator, col_btn, col_del = st.columns([0.07, 5, 1])
                    with indicator:
                        st.markdown(
                            '<div style="width:3px;height:28px;'
                            'background:#4F6EF7;border-radius:3px;'
                            'margin-top:4px;box-shadow:0 0 6px '
                            'rgba(79,110,247,0.5);"></div>',
                            unsafe_allow_html=True,
                        )
                else:
                    col_btn, col_del = st.columns([5, 1])

                with col_btn:
                    label = f"📌 {title}" if is_active else title
                    if st.button(
                        label,
                        key=f"sidebar_btn_{sid}_{idx}",
                        width="stretch",
                    ):
                        _switch_session(sid)
                with col_del:
                    if st.button(
                        "🗑️",
                        key=f"sidebar_del_{sid}_{idx}",
                    ):
                        _delete_session(client, sid)

        st.divider()
        st.caption("ElephantRAG v1.0")
