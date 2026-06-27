"""
智能问答页面
================================================
通过 ApiClient 与 FastAPI 后端通信，SSE 流式展示对话。
"""
import json
import time

import streamlit as st

from ui.api_client import ApiClient


def chat_page() -> None:
    """智能问答页面"""
    st.title("📄 知识库智能助手")
    st.caption("选择知识库并上传文档后，即可基于文档内容提问。支持 PDF、Word、Excel、TXT 等格式")
    st.divider()

    client = ApiClient()

    # ── 显示消息历史 ──
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # ── 用户输入 ──
    prompt = st.chat_input("输入你的查询问题...")

    if prompt:
        kb_name = st.session_state.get("kb_name", "default")
        session_id = st.session_state.get("session_id")

        # 显示用户消息
        with st.chat_message("user"):
            st.markdown(prompt)

        # 保存到 session_state
        st.session_state["messages"].append({"role": "user", "content": prompt})

        # 流式获取助手回复
        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            new_session_id = None

            try:
                for event_type, data in client.chat_stream(prompt, kb_name, session_id):
                    if event_type == "token":
                        full_response += data["token"]
                        response_placeholder.markdown(full_response + "▌")
                    elif event_type == "metadata":
                        new_session_id = data["metadata"]["session_id"]
                    elif event_type == "done":
                        pass
                    elif event_type == "error":
                        st.error(f"请求出错: {data.get('error', '未知错误')}")

                response_placeholder.markdown(full_response)

                # 更新 session_id
                if new_session_id:
                    st.session_state["session_id"] = new_session_id

                # 保存到历史
                if full_response:
                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": full_response,
                    })

                # 刷新会话列表
                st.rerun()

            except Exception as e:
                st.error(f"对话请求失败: {e}")
                st.session_state["messages"].append({
                    "role": "assistant",
                    "content": f"抱歉，请求失败: {str(e)}",
                })
