"""
对话路由 — SSE 流式问答 + 会话管理
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from core.logger import logger
from chat.store import ChatStore
from agent.react_agent import ReactAgent
from kb.manager import init_kb_manager

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Request / Response Models ──

class ChatRequest(BaseModel):
    content: str
    kb_name: str = "default"
    session_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    kb_name: str = "default"
    title: str = "新对话"


class UpdateTitleRequest(BaseModel):
    title: str


class SessionResponse(BaseModel):
    session_id: str
    title: str
    kb_name: str
    created_at: str
    updated_at: str


# ── Lazy Initialisation ──

_store: Optional[ChatStore] = None
_agent: Optional[ReactAgent] = None


def _ensure_store() -> ChatStore:
    global _store
    if _store is None:
        _store = ChatStore()
    return _store


def _ensure_agent() -> ReactAgent:
    global _agent
    if _agent is None:
        init_kb_manager()
        _agent = ReactAgent()
    return _agent


# ── SSE Streaming Chat ──

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat via SSE — sends tokens as ``data`` events,
    then a final ``done`` event with the session id.

    Event flow::

        data: {"token": "你好"}
        data: {"token": "世界"}
        ...
        data: {"metadata": {"session_id": "..."}}
        event: done
        data: {"session_id": "..."}

    On error::

        data: {"error": "..."}
    """
    store = _ensure_store()
    agent = _ensure_agent()

    # Get or create session
    session_id = store.get_or_create_session(request.session_id, request.kb_name)

    # Save user message
    store.add_message(session_id, "user", request.content)

    # Get history for agent context
    history = store.build_history(session_id)

    async def event_generator():
        full_response = ""
        try:
            for chunk in agent.execute_stream(request.content, history):
                full_response += chunk
                yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            # Save assistant message
            store.add_message(session_id, "assistant", full_response)

            # Auto-generate title from first exchange
            session = store.get_session(session_id)
            if session and session["title"] == "新对话":
                title = request.content[:30] + ("..." if len(request.content) > 30 else "")
                store.update_title(session_id, title)

            # Send metadata and done
            yield f"data: {json.dumps({'metadata': {'session_id': session_id}}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n"
        except Exception as e:
            logger.error(f"[Chat SSE] 流式生成失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ── Session Management ──

@router.post("/session/create", response_model=SessionResponse)
def create_session(req: CreateSessionRequest):
    """Create a new chat session."""
    store = _ensure_store()
    session_id = store.create_session(req.kb_name, req.title)
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=500, detail="创建会话失败")
    return SessionResponse(
        session_id=session["id"],
        title=session["title"],
        kb_name=session["kb_name"],
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )


@router.get("/session/list")
def list_sessions():
    """List all sessions, ordered by ``updated_at`` descending."""
    store = _ensure_store()
    sessions = store.list_sessions()
    return [
        SessionResponse(
            session_id=s["id"],
            title=s["title"],
            kb_name=s["kb_name"],
            created_at=s["created_at"],
            updated_at=s["updated_at"],
        )
        for s in sessions
    ]


@router.get("/session/{session_id}/messages")
def get_session_messages(session_id: str):
    """Get all messages for a session."""
    store = _ensure_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = store.get_messages(session_id)
    return {
        "session_id": session_id,
        "messages": messages,
    }


@router.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session and all its messages."""
    store = _ensure_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    store.delete_session(session_id)
    return {"detail": "会话已删除"}


@router.put("/session/{session_id}/title")
def update_session_title(session_id: str, req: UpdateTitleRequest):
    """Update the title of a session."""
    store = _ensure_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    store.update_title(session_id, req.title)
    return {"detail": "标题已更新"}
