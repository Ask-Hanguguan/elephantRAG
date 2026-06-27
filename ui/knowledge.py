"""
知识库管理页面 — 上传/列表/下载/删除/重向量化

通过 ApiClient 与 FastAPI 后端通信，不再直接操作 Python 模块。
"""
import os
from typing import Optional

import streamlit as st
import pandas as pd

from ui.api_client import ApiClient


def _get_client() -> ApiClient:
    return ApiClient()


def knowledge_page() -> None:
    """知识库管理主页面"""
    st.subheader("📁 知识库管理")

    client = _get_client()

    # ── 知识库选择/创建 ──
    col1, col2 = st.columns([3, 1])
    with col1:
        try:
            kb_list = client.list_knowledge_bases()
            st.session_state["kb_list"] = kb_list
        except Exception as e:
            st.error(f"无法获取知识库列表: {e}")
            kb_list = st.session_state.get("kb_list", [])

        current_kb = st.session_state.get("kb_name", "default")
        if kb_list:
            selected_kb = st.selectbox(
                "选择知识库",
                kb_list,
                index=kb_list.index(current_kb) if current_kb in kb_list else 0,
                key="kb_selector",
            )
            if selected_kb != current_kb:
                try:
                    client.switch_knowledge_base(selected_kb)
                    st.session_state["kb_name"] = selected_kb
                    st.rerun()
                except Exception as e:
                    st.error(f"切换知识库失败: {e}")
        else:
            st.info("暂无知识库，请创建一个")

    with col2:
        with st.popover("➕ 新建"):
            new_kb_name = st.text_input("知识库名称", key="new_kb_name")
            if st.button("创建", key="create_kb_btn"):
                if new_kb_name:
                    try:
                        client.create_knowledge_base(new_kb_name)
                        st.success(f"知识库 '{new_kb_name}' 创建成功")
                        st.session_state["kb_name"] = new_kb_name
                        st.rerun()
                    except Exception as e:
                        st.error(f"创建失败: {e}")
                else:
                    st.warning("请输入知识库名称")

    st.divider()

    # ── 上传文档 ──
    kb_name = st.session_state.get("kb_name", "default")
    st.subheader(f"📤 上传文档到「{kb_name}」")

    uploaded_files = st.file_uploader(
        "选择文件",
        type=["pdf", "txt", "md", "csv", "html", "docx", "xlsx", "pptx"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        if st.button("开始上传", type="primary", key="upload_btn"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, uploaded_file in enumerate(uploaded_files):
                try:
                    status_text.text(f"正在上传: {uploaded_file.name}")
                    file_bytes = uploaded_file.getvalue()
                    client.upload_document(kb_name, file_bytes, uploaded_file.name)
                except Exception as e:
                    st.error(f"上传失败 {uploaded_file.name}: {e}")

                progress_bar.progress((i + 1) / len(uploaded_files))

            status_text.text("上传完成！")
            st.success(f"成功上传 {len(uploaded_files)} 个文件")
            st.rerun()

    st.divider()

    # ── 文档列表 ──
    st.subheader("📋 文档列表")

    try:
        docs = client.list_documents(kb_name)
    except Exception as e:
        st.error(f"获取文档列表失败: {e}")
        docs = []

    if not docs:
        st.info("知识库中暂无文档，请上传。")
        return

    # 构建展示表格
    df_data = []
    for doc in docs:
        file_size = doc.get("file_size", 0)
        size_str = (
            f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024
            else f"{file_size / 1024 / 1024:.1f} MB"
        )
        df_data.append({
            "ID": doc["id"],
            "文件名": doc["file_name"],
            "大小": size_str,
            "状态": doc.get("status", "unknown"),
            "Chunks": doc.get("chunk_count", 0),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 文档操作（每行一个） ──
    st.subheader("🔧 文档操作")

    doc_options = {d["file_name"]: d["id"] for d in docs}
    selected_name = st.selectbox("选择文档", list(doc_options.keys()), key="doc_ops")
    selected_id = doc_options[selected_name]

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        if st.button("📥 下载", key="download_btn"):
            try:
                file_bytes, filename = client.download_document(kb_name, selected_id)
                st.download_button(
                    label="点击保存文件",
                    data=file_bytes,
                    file_name=filename,
                    mime="application/octet-stream",
                )
            except Exception as e:
                st.error(f"下载失败: {e}")

    with col_b:
        if st.button("🔄 重向量化", key="revectorize_btn", type="secondary"):
            try:
                with st.spinner("正在重新向量化..."):
                    client.revectorize_document(kb_name, selected_id)
                st.success("重新向量化成功！")
                st.rerun()
            except Exception as e:
                st.error(f"重向量化失败: {e}")

    with col_c:
        if st.button("🗑️ 删除", key="delete_btn", type="secondary"):
            try:
                client.delete_document(kb_name, selected_id)
                st.success("删除成功！")
                st.rerun()
            except Exception as e:
                st.error(f"删除失败: {e}")

    with col_d:
        st.write("")  # 占位
