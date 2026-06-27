"""
FastAPI HTTP 客户端封装 — Streamlit 前端通过此模块与后端通信

提供同步和异步两种调用方式，支持 SSE 流式解析。
"""

import json
import os
from typing import Optional, BinaryIO
from io import BytesIO

import httpx
import streamlit as st

from core.logger import logger

# 后端地址，优先从环境变量或 st.secrets 读取
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


class ApiClient:
    """FastAPI HTTP 客户端"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ── 知识库接口 ──

    def list_knowledge_bases(self) -> list[str]:
        """列出所有知识库"""
        resp = httpx.get(f"{self.base_url}/api/kb/list", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("knowledge_bases", [])

    def create_knowledge_base(self, name: str) -> dict:
        """创建知识库"""
        resp = httpx.post(
            f"{self.base_url}/api/kb/create",
            json={"name": name},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def switch_knowledge_base(self, name: str) -> dict:
        """切换当前知识库"""
        resp = httpx.post(
            f"{self.base_url}/api/kb/switch",
            json={"name": name},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 文档接口 ──

    def list_documents(self, kb_name: str) -> list[dict]:
        """获取文档列表"""
        resp = httpx.get(
            f"{self.base_url}/api/kb/{kb_name}/documents",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("documents", [])

    def upload_document(self, kb_name: str, file_data: bytes, filename: str) -> dict:
        """上传文档"""
        files = {"file": (filename, file_data)}
        resp = httpx.post(
            f"{self.base_url}/api/kb/{kb_name}/upload",
            files=files,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def download_document(self, kb_name: str, doc_id: int) -> tuple[bytes, str]:
        """下载文档，返回 (bytes, filename)"""
        resp = httpx.get(
            f"{self.base_url}/api/kb/{kb_name}/documents/{doc_id}/download",
            timeout=30,
        )
        resp.raise_for_status()
        disposition = resp.headers.get("content-disposition", "")
        filename = "unknown"
        if "filename=" in disposition:
            filename = disposition.split("filename=")[-1].strip('"')
        return resp.content, filename

    def delete_document(self, kb_name: str, doc_id: int) -> dict:
        """删除文档（含向量+BM25）"""
        resp = httpx.delete(
            f"{self.base_url}/api/kb/{kb_name}/documents/{doc_id}",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def revectorize_document(self, kb_name: str, doc_id: int) -> dict:
        """重新向量化"""
        resp = httpx.post(
            f"{self.base_url}/api/kb/{kb_name}/documents/{doc_id}/revectorize",
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 会话接口 ──

    def create_session(self, kb_name: str = "default", title: str = "新对话") -> dict:
        """创建新会话"""
        resp = httpx.post(
            f"{self.base_url}/api/chat/session/create",
            json={"kb_name": kb_name, "title": title},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        resp = httpx.get(
            f"{self.base_url}/api/chat/session/list",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_session_messages(self, session_id: str) -> list[dict]:
        """获取会话消息历史"""
        resp = httpx.get(
            f"{self.base_url}/api/chat/session/{session_id}/messages",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_session(self, session_id: str) -> dict:
        """删除会话"""
        resp = httpx.delete(
            f"{self.base_url}/api/chat/session/{session_id}",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def update_session_title(self, session_id: str, title: str) -> dict:
        """更新会话标题"""
        resp = httpx.put(
            f"{self.base_url}/api/chat/session/{session_id}/title",
            json={"title": title},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 对话 SSE 流 ──

    def chat_stream(self, content: str, kb_name: str, session_id: Optional[str] = None):
        """RAG 对话 SSE 流式请求

        返回生成器，产出 (event_type, data_dict) 元组
        event_type: 'token' | 'metadata' | 'done' | 'error'
        """
        payload = {
            "content": content,
            "kb_name": kb_name,
            "session_id": session_id,
        }

        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat/stream",
            json=payload,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        if "token" in data:
                            yield ("token", data)
                        elif "metadata" in data:
                            yield ("metadata", data)
                        elif "error" in data:
                            yield ("error", data)
                    except json.JSONDecodeError:
                        logger.warning(f"[ApiClient] 无法解析 SSE data: {data_str}")
                elif line.startswith("event: done"):
                    yield ("done", {})
                elif line.startswith("event: "):
                    # 非 data 事件暂不处理
                    pass
