"""
知识库管理页面 — 上传/列表/下载/删除/重向量化

通过 ApiClient 与 FastAPI 后端通信，不再直接操作 Python 模块。
"""
import os
import time
from typing import Optional

import streamlit as st
import pandas as pd

from ui.api_client import ApiClient


def _get_client() -> ApiClient:
    return ApiClient()


def _render_kb_header(client: ApiClient) -> str:
    """渲染管理知识库选择 + 创建，返回当前 manage_kb"""
    col1, col2 = st.columns([3, 1])
    with col1:
        try:
            kb_list = client.list_knowledge_bases()
        except Exception:
            kb_list = st.session_state.get("kb_list", [])

        current_mkb = st.session_state.get("manage_kb", "default")
        if kb_list:
            if current_mkb not in kb_list:
                current_mkb = kb_list[0]
                st.session_state["manage_kb"] = current_mkb
            selected_kb = st.selectbox(
                "选择知识库",
                kb_list,
                index=kb_list.index(current_mkb) if current_mkb in kb_list else 0,
                key="knowledge_kb_selector",
                help="管理文档操作的知识库",
            )
            if selected_kb != current_mkb:
                st.session_state["manage_kb"] = selected_kb
                st.rerun()
        else:
            st.info("暂无知识库，请创建一个")
            selected_kb = current_mkb

    with col2:
        with st.popover("➕ 新建"):
            new_kb_name = st.text_input("知识库名称", key="new_kb_name")
            if st.button("创建", key="create_kb_btn"):
                if new_kb_name:
                    try:
                        client.create_knowledge_base(new_kb_name)
                        st.success(f"知识库 '{new_kb_name}' 创建成功")
                        st.session_state["manage_kb"] = new_kb_name
                        st.rerun()
                    except Exception as e:
                        st.error(f"创建失败: {e}")
                else:
                    st.warning("请输入知识库名称")

    return selected_kb


def _render_file_upload(client: ApiClient, kb_name: str):
    """渲染文件上传区，使用 st.status 提供清晰的状态反馈"""
    uploaded_files = st.file_uploader(
        "选择文件",
        type=["pdf", "txt", "md", "csv", "html", "docx", "xlsx", "pptx"],
        accept_multiple_files=True,
        key="knowledge_file_uploader",
        help="支持 PDF / Word / Excel / PPT / Markdown / TXT / CSV / HTML",
    )

    if not uploaded_files:
        return

    # 显示待上传文件列表
    with st.expander(f"📋 已选择 {len(uploaded_files)} 个文件", expanded=True):
        for f in uploaded_files:
            size_kb = len(f.getvalue()) / 1024
            st.caption(f"📄 {f.name} ({size_kb:.1f} KB)")

    if not st.button("🚀 开始上传", type="primary", key="upload_btn"):
        return

    # ── 用 st.status 包裹，视觉反馈清晰 ──
    success_count = 0
    fail_count = 0

    with st.status("正在处理文档...", expanded=True) as status:
        for i, uploaded_file in enumerate(uploaded_files):
            file_name = uploaded_file.name
            file_size = len(uploaded_file.getvalue()) / 1024
            st.write(f"⏳ [{i + 1}/{len(uploaded_files)}] {file_name} ({file_size:.1f} KB)")
            try:
                file_bytes = uploaded_file.getvalue()
                result = client.upload_document(kb_name, file_bytes, file_name)
                chunks = result.get("document", {}).get("chunk_count", "?")
                st.write(f"✅ {file_name} → {chunks} chunks 已入库")
                success_count += 1
            except Exception as e:
                st.write(f"❌ {file_name} 上传失败: {e}")
                fail_count += 1
            time.sleep(0.1)  # 给 Streamlit 渲染留出间隙

        # 更新 status 状态
        if fail_count == 0:
            status.update(label=f"全部上传完成！({success_count} 个文件)", state="complete")
        else:
            status.update(
                label=f"上传完成：{success_count} 成功 / {fail_count} 失败", state="complete"
            )

    if success_count > 0:
        st.success(f"✅ 成功入库 {success_count} 个文档")
    if fail_count > 0:
        st.error(f"❌ {fail_count} 个文档上传失败")

    st.rerun()


def _render_doc_table(client: ApiClient, kb_name: str):
    """渲染文档列表表格"""
    try:
        docs = client.list_documents(kb_name)
    except Exception as e:
        st.error(f"获取文档列表失败: {e}")
        docs = []

    if not docs:
        st.info("知识库中暂无文档，请上传。")
        return None

    df_data = []
    status_label = {
        "uploaded": "未向量化",
        "vectorized": "已向量化",
        "processing": "处理中",
    }
    for doc in docs:
        file_size = doc.get("file_size", 0)
        if file_size < 1024:
            size_str = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / 1024 / 1024:.1f} MB"

        raw_status = doc.get("status", "")
        df_data.append({
            "ID": doc["id"],
            "文件名": doc["file_name"],
            "大小": size_str,
            "状态": status_label.get(raw_status, raw_status),
            "Chunks": doc.get("chunk_count", 0),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, width="stretch", hide_index=True)
    return {d["file_name"]: d["id"] for d in docs}


def _render_doc_actions(client: ApiClient, kb_name: str, doc_options: dict):
    """渲染文档操作按钮"""
    selected_name = st.selectbox("选择文档", list(doc_options.keys()), key="doc_ops")
    selected_id = doc_options[selected_name]

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("📥 下载", key="download_btn", width="stretch"):
            try:
                file_bytes, filename = client.download_document(kb_name, selected_id)
                st.session_state["dl_data"] = file_bytes
                st.session_state["dl_name"] = filename
            except Exception as e:
                st.error(f"下载失败: {e}")

    # 下载按钮在 button click 后立即渲染（同一次 run）
    if "dl_data" in st.session_state and "dl_name" in st.session_state:
        st.download_button(
            label=f"💾 保存 {st.session_state['dl_name']}",
            data=st.session_state["dl_data"],
            file_name=st.session_state["dl_name"],
            mime="application/octet-stream",
            key="save_btn",
        )

    with col_b:
        if st.button("🔄 重向量化", key="revectorize_btn", width="stretch"):
            try:
                with st.spinner("正在重新向量化..."):
                    client.revectorize_document(kb_name, selected_id)
                st.success(f"「{selected_name}」重新向量化完成")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"重向量化失败: {e}")

    with col_c:
        if st.button("🗑️ 删除", key="delete_btn", width="stretch"):
            try:
                client.delete_document(kb_name, selected_id)
                st.success(f"「{selected_name}」已删除")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"删除失败: {e}")


def knowledge_page() -> None:
    """知识库管理主页面"""
    st.subheader("📁 知识库管理")
    client = _get_client()

    # ── 知识库选择 ──
    kb_name = _render_kb_header(client)
    st.divider()

    # ── 上传文档 ──
    st.subheader(f"📤 上传文档到「{kb_name}」")
    _render_file_upload(client, kb_name)
    st.divider()

    # ── 文档列表 ──
    st.subheader("📋 文档列表")
    doc_options = _render_doc_table(client, kb_name)
    if doc_options:
        st.divider()
        st.subheader("🔧 文档操作")
        _render_doc_actions(client, kb_name, doc_options)
