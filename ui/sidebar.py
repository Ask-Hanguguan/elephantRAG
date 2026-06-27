"""
侧边栏
================================================
知识库选择器 + 会话列表 — 无认证信息。
"""
import streamlit as st

from ui.api_client import ApiClient
from core.logger import logger


def _refresh_sessions(client: ApiClient):
    """刷新会话列表"""
    try:
        sessions = client.list_sessions()
        st.session_state["session_list"] = sessions
    except Exception as e:
        logger.warning(f"[Sidebar] 获取会话列表失败: {e}")
        st.session_state["session_list"] = []


def _switch_session(session_id: str):
    """切换会话，加载历史消息"""
    client = ApiClient()
    try:
        messages = client.get_session_messages(session_id)
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = messages if messages else [
            {"role": "assistant", "content": "你好，我是知识库智能助手！"}
        ]
    except Exception as e:
        logger.error(f"[Sidebar] 加载会话失败: {e}")


def sidebar() -> None:
    """侧边栏：知识库选择器 + 会话管理"""
    client = ApiClient()

    with st.sidebar:
        st.subheader("🧠 ElephantRAG")

        # ── 知识库选择 ──
        st.markdown("### 📚 当前知识库")
        try:
            kbs = client.list_knowledge_bases()
            if kbs:
                current_kb = st.session_state.get("kb_name", "default")
                if current_kb not in kbs:
                    current_kb = kbs[0]
                    st.session_state["kb_name"] = current_kb
                selected = st.selectbox(
                    "选择知识库",
                    kbs,
                    index=kbs.index(current_kb) if current_kb in kbs else 0,
                    key="sidebar_kb_selector",
                    label_visibility="collapsed",
                )
                if selected != current_kb:
                    try:
                        client.switch_knowledge_base(selected)
                        st.session_state["kb_name"] = selected
                        # 切换 KB 时创建新会话
                        new_session = client.create_session(kb_name=selected)
                        st.session_state["session_id"] = new_session.get("session_id")
                        st.session_state["messages"] = [
                            {"role": "assistant", "content": f"已切换到知识库「{selected}」"}
                        ]
                        _refresh_sessions(client)
                        st.rerun()
                    except Exception as e:
                        st.error(f"切换失败: {e}")
        except Exception as e:
            st.warning(f"无法连接后端服务: {e}")

        st.divider()

        # ── 会话列表 ──
        st.markdown("### 💬 会话历史")

        if st.button("➕ 新对话", use_container_width=True, type="primary"):
            try:
                kb_name = st.session_state.get("kb_name", "default")
                new_session = client.create_session(kb_name=kb_name)
                st.session_state["session_id"] = new_session.get("session_id")
                st.session_state["messages"] = [
                    {"role": "assistant", "content": "你好，我是知识库智能助手！有什么可以帮助你的？"}
                ]
                _refresh_sessions(client)
                st.rerun()
            except Exception as e:
                st.error(f"创建会话失败: {e}")

        # 显示会话列表
        sessions = st.session_state.get("session_list", [])
        if not sessions:
            try:
                sessions = client.list_sessions()
                st.session_state["session_list"] = sessions
            except Exception:
                pass

        if sessions:
            current_sid = st.session_state.get("session_id")
            for idx, s in enumerate(sessions[:20]):  # 最多显示20个
                title = s.get("title", "新对话")[:20]
                kb_tag = s.get("kb_name", "")
                sid = s.get("id")
                # 确保 key 唯一（sid 可能为空）
                unique_key = sid or f"session_idx_{idx}"
                is_active = sid and sid == current_sid

                label = f"{'📌 ' if is_active else ''}{title}{'...' if len(title) >= 20 else ''}"
                if st.button(
                    label,
                    key=f"sidebar_{unique_key}",
                    use_container_width=True,
                    type="secondary" if not is_active else "primary",
                    help=f"知识库: {kb_tag}",
                ):
                    if sid:
                        _switch_session(sid)
                        st.rerun()

        # ── 底部信息 ──
        st.divider()
        st.caption("ElephantRAG v1.0")
