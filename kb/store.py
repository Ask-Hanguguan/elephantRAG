"""
每个知识库独立的信息存储 — info.db 文档元数据 + BM25 tokens
"""

import sqlite3
from datetime import datetime
from typing import Any


class KBStore:
    """Per-knowledge-base document metadata and BM25 token store backed by SQLite."""

    def __init__(self, kb_path: str) -> None:
        """Create or open info.db at kb_path/info.db and auto-create tables."""
        self._db_path = f"{kb_path}/info.db"
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        self._conn.executescript("""
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
        self._conn.commit()

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
        cur = self._conn.execute(
            """
            INSERT INTO documents
                (file_name, file_path, md5, file_size, file_type,
                 status, chunk_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'uploaded', 0, ?, ?)
            """,
            (file_name, file_path, md5, file_size, file_type, now, now),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_document(self, doc_id: int) -> dict[str, Any] | None:
        """Return a document dict by id, or None."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_documents(self) -> list[dict[str, Any]]:
        """Return all documents ordered by created_at descending."""
        rows = self._conn.execute(
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
        if chunk_count is not None:
            self._conn.execute(
                """
                UPDATE documents
                   SET status = ?, chunk_count = ?, updated_at = ?
                 WHERE id = ?
                """,
                (status, chunk_count, now, doc_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE documents
                   SET status = ?, updated_at = ?
                 WHERE id = ?
                """,
                (status, now, doc_id),
            )
        self._conn.commit()

    def update_md5(self, doc_id: int, md5: str) -> None:
        """Update document md5 (e.g. for re-vectorization)."""
        now = self._now()
        self._conn.execute(
            "UPDATE documents SET md5 = ?, updated_at = ? WHERE id = ?",
            (md5, now, doc_id),
        )
        self._conn.commit()

    def delete_document(self, doc_id: int) -> None:
        """Remove a document row by id."""
        self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()

    def get_document_by_md5(self, md5: str) -> dict[str, Any] | None:
        """Return the first document matching the given md5, or None."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE md5 = ?", (md5,)
        ).fetchone()
        return self._row_to_dict(row)

    def get_document_by_path(self, file_path: str) -> dict[str, Any] | None:
        """Return the first document matching the given file_path, or None."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE file_path = ?", (file_path,)
        ).fetchone()
        return self._row_to_dict(row)

    def get_all_md5s(self) -> set[str]:
        """Return the set of all md5 values in the documents table."""
        rows = self._conn.execute("SELECT md5 FROM documents").fetchall()
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
        self._conn.execute(
            """
            INSERT OR REPLACE INTO bm25_tokens
                (chunk_id, tokens, doc_length, doc_preview, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chunk_id, tokens, doc_length, doc_preview, now),
        )
        self._conn.commit()

    def get_bm25_tokens(self) -> list[dict[str, Any]]:
        """Return all BM25 token rows."""
        rows = self._conn.execute(
            "SELECT * FROM bm25_tokens"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_bm25_tokens_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """Delete BM25 token rows matching the given chunk ids."""
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        self._conn.execute(
            f"DELETE FROM bm25_tokens WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # BM25 metadata
    # ------------------------------------------------------------------

    def get_bm25_meta(self, key: str) -> str | None:
        """Return the value for a given bm25_meta key, or None."""
        row = self._conn.execute(
            "SELECT value FROM bm25_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_bm25_meta(self, key: str, value: str) -> None:
        """Insert or replace a bm25_meta key-value pair."""
        self._conn.execute(
            "INSERT OR REPLACE INTO bm25_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
