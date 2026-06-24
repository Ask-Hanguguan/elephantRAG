"""
文档管理页面
================================================
"""
import os
import time
import threading

import streamlit as st

from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


def documents_page() -> None:
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

            try:
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            except Exception as e:
                st.error(f"文件保存失败: {str(e)}")
                return

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

    from agent.tools.agent_tools import vector_store

    md5_records = vector_store.md5_store.get_all_records()

    current_ingest = st.session_state.get("_ingest_file", "")
    current_thread = st.session_state.get("_ingest_thread")

    for fname in files:
        fpath = os.path.join(data_path, fname)
        size_kb = os.path.getsize(fpath) / 1024

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


def _check_ingest_result() -> None:
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


def _start_ingest_thread(file_path: str, file_name: str) -> None:
    """启动后台入库线程"""
    current = st.session_state.get("_ingest_thread")
    if current and current.is_alive():
        st.warning(f"已有文件正在入库 ({st.session_state.get('_ingest_file', '')})，请等待完成")
        return

    logger.info(f"[后台入库] 启动: {file_name}")

    def _run() -> None:
        try:
            from agent.tools.agent_tools import vector_store

            vector_store.load_single_document(file_path)
            st.session_state["_ingest_result"] = {"ok": True, "name": file_name}
            logger.info(f"[后台入库] 完成: {file_name}")
        except Exception as e:
            st.session_state["_ingest_result"] = {
                "ok": False,
                "name": file_name,
                "error": str(e),
            }
            logger.error(f"[后台入库] 失败: {file_name} - {str(e)}", exc_info=True)

    t = threading.Thread(target=_run, daemon=True)
    st.session_state["_ingest_thread"] = t
    st.session_state["_ingest_file"] = file_name
    t.start()
    st.info(f"⏳ 已启动后台入库: {file_name}，可切换页面")
    time.sleep(0.5)
    st.rerun()
