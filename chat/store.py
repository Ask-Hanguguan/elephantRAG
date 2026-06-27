"""
对话持久化模块 — ChatStore

使用 SQLite 存储会话和消息记录，独立于知识库数据。
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from core.path import get_abs_path

DB_PATH = get_abs_path("data/chat/chat.db")


class ChatStore:
    """对话存储，管理会话与消息的 CRUD"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id            TEXT PRIMARY KEY,
                    title         TEXT NOT NULL DEFAULT '新对话',
                    kb_name       TEXT NOT NULL,
                    created_at    TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    metadata        TEXT,
                    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
            """)
            conn.commit()
        finally:
            conn.close()

    # ── 会话操作 ──

    def create_session(self, kb_name: str, title: str = "新对话") -> str:
        session_id = str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO conversations (id, title, kb_name) VALUES (?, ?, ?)",
                (session_id, title, kb_name),
            )
            conn.commit()
            return session_id
        finally:
            conn.close()

    def list_sessions(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_title(self, session_id: str, title: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (title, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_session(self, session_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM conversations WHERE id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()

    # ── 消息操作 ──

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> int:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata, ensure_ascii=False) if metadata else None),
            )
            # 更新会话 updated_at
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now', 'localtime') WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_messages(self, session_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            result = []
            for r in rows:
                msg = dict(r)
                if msg.get("metadata"):
                    try:
                        msg["metadata"] = json.loads(msg["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append(msg)
            return result
        finally:
            conn.close()

    # ── 工具方法 ──

    def get_or_create_session(self, session_id: Optional[str], kb_name: str) -> str:
        """获取已有 session，不存在则创建新会话"""
        if session_id and self.get_session(session_id):
            return session_id
        return self.create_session(kb_name)

    def build_history(self, session_id: str, max_turns: int = 20) -> list[dict]:
        """构建给 Agent 的消息历史（截断早期轮次，保留 system prompt 空间）"""
        messages = self.get_messages(session_id)
        # 只保留 user 和 assistant 消息
        filtered = [m for m in messages if m["role"] in ("user", "assistant")]
        # 截断到最近 max_turns 轮（1轮 = 1 user + 1 assistant）
        if len(filtered) > max_turns * 2:
            filtered = filtered[-max_turns * 2:]
        return filtered
