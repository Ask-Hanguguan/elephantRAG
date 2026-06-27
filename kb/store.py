"""
每个知识库独立的信息存储 — info.db 文档元数据 + BM25 tokens

线程安全：使用 ``threading.local()`` 为每个线程维护独立连接，
避免 FastAPI 多线程请求时的 SQLite 跨线程错误。
"""

import sqlite3
import threading
from datetime import datetime
from typing import Any


class KBStore:
    """Per-knowledge-base document metadata and BM25 token store backed by SQLite.

    Each thread gets its own ``sqlite3.Connection`` via ``threading.local()``.
    Table creation and write operations are serialized with ``threading.Lock``.
    """

    def __init__(self, kb_path: str) -> None:
        self._db_path = f"{kb_path}/info.db"
        self._lock = threading.Lock()
        self._local = threading.local()

        # Create tables on the calling thread
        conn = self._get_conn()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        self._create_tables(conn)

    # ------------------------------------------------------------------
    # connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection, creating one if needed."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                md5 TEXT NOT NULL,
                file_size INTEGER,
                file_type TEXT,
                status TEXT DEFAULT 'uploaded',
                chunk_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bm25_tokens (
                chunk_id TEXT PRIMARY KEY,
                tokens TEXT NOT NULL,
                doc_length INTEGER NOT NULL,
                doc_preview TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bm25_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(sep=" ", timespec="seconds")

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # document CRUD
    # ------------------------------------------------------------------

    def add_document(
        self,
        file_name: str,
        file_path: str,
        md5: str,
        file_size: int,
        file_type: str,
    ) -> int:
        """Insert a document row and return the new doc_id."""
        now = self._now()
        conn = self._get_conn()
        with self._lock:
            cur = conn.execute(
                """
                INSERT INTO documents
                    (file_name, file_path, md5, file_size, file_type,
                     status, chunk_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'uploaded', 0, ?, ?)
                """,
                (file_name, file_path, md5, file_size, file_type, now, now),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def get_document(self, doc_id: int) -> dict[str, Any] | None:
        """Return a document dict by id, or None."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            return self._row_to_dict(row)

    def list_documents(self) -> list[dict[str, Any]]:
        """Return all documents ordered by created_at descending."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_status(
        self,
        doc_id: int,
        status: str,
        chunk_count: int | None = None,
    ) -> None:
        """Update document status and optionally chunk_count."""
        now = self._now()
        conn = self._get_conn()
        with self._lock:
            if chunk_count is not None:
                conn.execute(
                    """
                    UPDATE documents
                       SET status = ?, chunk_count = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (status, chunk_count, now, doc_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE documents
                       SET status = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (status, now, doc_id),
                )
            conn.commit()

    def update_md5(self, doc_id: int, md5: str) -> None:
        """Update document md5 (e.g. for re-vectorization)."""
        now = self._now()
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "UPDATE documents SET md5 = ?, updated_at = ? WHERE id = ?",
                (md5, now, doc_id),
            )
            conn.commit()

    def delete_document(self, doc_id: int) -> None:
        """Remove a document row by id."""
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()

    def get_document_by_md5(self, md5: str) -> dict[str, Any] | None:
        """Return the first document matching the given md5, or None."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM documents WHERE md5 = ?", (md5,)
            ).fetchone()
            return self._row_to_dict(row)

    def get_document_by_path(self, file_path: str) -> dict[str, Any] | None:
        """Return the first document matching the given file_path, or None."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM documents WHERE file_path = ?", (file_path,)
            ).fetchone()
            return self._row_to_dict(row)

    def get_all_md5s(self) -> set[str]:
        """Return the set of all md5 values in the documents table."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute("SELECT md5 FROM documents").fetchall()
            return {r["md5"] for r in rows}

    # ------------------------------------------------------------------
    # BM25 tokens
    # ------------------------------------------------------------------

    def save_bm25_tokens(
        self,
        chunk_id: str,
        tokens: str,
        doc_length: int,
        doc_preview: str,
    ) -> None:
        """Insert or replace a BM25 token row."""
        now = self._now()
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                """
                INSERT OR REPLACE INTO bm25_tokens
                    (chunk_id, tokens, doc_length, doc_preview, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chunk_id, tokens, doc_length, doc_preview, now),
            )
            conn.commit()

    def get_bm25_tokens(self) -> list[dict[str, Any]]:
        """Return all BM25 token rows."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT * FROM bm25_tokens"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_bm25_tokens_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """Delete BM25 token rows matching the given chunk ids."""
        if not chunk_ids:
            return
        conn = self._get_conn()
        with self._lock:
            placeholders = ",".join("?" for _ in chunk_ids)
            conn.execute(
                f"DELETE FROM bm25_tokens WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # BM25 metadata
    # ------------------------------------------------------------------

    def get_bm25_meta(self, key: str) -> str | None:
        """Return the value for a given bm25_meta key, or None."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT value FROM bm25_meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_bm25_meta(self, key: str, value: str) -> None:
        """Insert or replace a bm25_meta key-value pair."""
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO bm25_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the thread-local connection if open."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
