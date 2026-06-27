"""
知识库路由 — 文档上传/列表/下载/删除/重向量化
"""

import os
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.logger import logger
from kb.manager import init_kb_manager

router = APIRouter(prefix="/api/kb", tags=["knowledge"])


def _ensure_kb():
    """Ensure the KB manager is initialized (lazy singleton)."""
    return init_kb_manager()


class CreateKBRequest(BaseModel):
    """Request model for creating a knowledge base."""
    name: str


class SwitchKBRequest(BaseModel):
    """Request model for switching the current knowledge base."""
    name: str


@router.get("/list")
def list_knowledge_bases():
    """List all knowledge bases and return the current one."""
    mgr = _ensure_kb()
    kbs = mgr.list_knowledge_bases()
    return {"knowledge_bases": kbs, "current": mgr.get_current_kb_name()}


@router.post("/create")
async def create_knowledge_base(req: CreateKBRequest):
    """Create a new knowledge base."""
    mgr = _ensure_kb()
    success = mgr.create_knowledge_base(req.name)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"知识库 '{req.name}' 已存在",
        )
    return {"message": f"知识库 '{req.name}' 创建成功"}


@router.post("/switch")
async def switch_knowledge_base(req: SwitchKBRequest):
    """Switch the current knowledge base."""
    mgr = _ensure_kb()
    if not mgr.kb_exists(req.name):
        raise HTTPException(
            status_code=404,
            detail=f"知识库 '{req.name}' 不存在",
        )
    mgr.set_current_kb(req.name)
    return {"message": f"已切换到知识库 '{req.name}'"}


@router.post("/{kb_name}/upload")
async def upload_document(kb_name: str, file: UploadFile = File(...)):
    """Upload a document to the specified knowledge base (multipart)."""
    mgr = _ensure_kb()
    if not mgr.kb_exists(kb_name):
        raise HTTPException(
            status_code=404,
            detail=f"知识库 '{kb_name}' 不存在",
        )

    content = await file.read()
    result = mgr.upload_document(BytesIO(content), file.filename, kb_name)
    return {"message": "上传成功", "document": result}


@router.get("/{kb_name}/documents")
def list_documents(kb_name: str):
    """List all documents in the specified knowledge base."""
    mgr = _ensure_kb()
    if not mgr.kb_exists(kb_name):
        raise HTTPException(
            status_code=404,
            detail=f"知识库 '{kb_name}' 不存在",
        )
    docs = mgr.list_documents(kb_name)
    return {"documents": docs}


@router.get("/{kb_name}/documents/{doc_id}/download")
def download_document(kb_name: str, doc_id: int):
    """Download a document from the specified knowledge base."""
    mgr = _ensure_kb()
    try:
        file_bytes, filename = mgr.download_document(doc_id, kb_name)
        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("下载文档失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_name}/documents/{doc_id}")
def delete_document(kb_name: str, doc_id: int):
    """Delete a document from the specified knowledge base."""
    mgr = _ensure_kb()
    try:
        mgr.delete_document(doc_id, kb_name)
        return {"message": "删除成功"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("删除文档失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/documents/{doc_id}/revectorize")
def revectorize_document(kb_name: str, doc_id: int):
    """Re-vectorize a document in the specified knowledge base."""
    mgr = _ensure_kb()
    try:
        mgr.revectorize_document(doc_id, kb_name)
        return {"message": "重新向量化成功"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("重新向量化失败")
        raise HTTPException(status_code=500, detail=str(e))
