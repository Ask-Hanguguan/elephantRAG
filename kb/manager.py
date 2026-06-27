"""
KBManager — 知识库注册表 & 生命周期管理

每个知识库物理独立:
  data/knowledge_base/{kb_name}/
    ├── info.db        → KBStore (文档元数据 + BM25 分词缓存)
    ├── content/       → 原始文档文件
    └── chroma_db/     → ChromaDB (通过 VectorStoreService)
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from typing import Any, Optional

from core.logger import logger
from core.path import get_abs_path
from kb.store import KBStore

REGISTRY_PATH = get_abs_path("data/knowledge_base/registry.json")
KB_ROOT = get_abs_path("data/knowledge_base")


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _get_file_md5_hex(file_path: str) -> str:
    """Compute MD5 hex digest of a file (streaming, memory-friendly)."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------
# KBManager singleton
# ------------------------------------------------------------------

class KBManager:
    """Central orchestrator for all knowledge base operations.

    Manages KB registration via registry.json, per-KB directory structure,
    and delegates to KBStore, VectorStoreService, BM25SparseIndex, and
    FusionRetriever for each KB.
    """

    def __init__(self) -> None:
        os.makedirs(KB_ROOT, exist_ok=True)
        self._registry: dict[str, Any] = self._load_registry()
        # Per-KB caches: name -> KBStore / VectorStoreService
        self._stores: dict[str, KBStore] = {}
        self._vector_stores: dict[str, Any] = {}

        # Auto-create 'default' KB when the registry is empty
        if not self._registry.get("kbs"):
            logger.info("Registry empty — creating default knowledge base")
            self.create_knowledge_base("default")
            self._registry["current"] = "default"
            self._save_registry()

    # ------------------------------------------------------------------
    # registry management
    # ------------------------------------------------------------------

    def _load_registry(self) -> dict:
        """Load registry.json, returning a dict with 'kbs' and 'current' keys."""
        if not os.path.isfile(REGISTRY_PATH):
            return {"kbs": {}, "current": None}
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # ── 旧格式迁移：列表 → 新字典格式 ──
            if isinstance(raw, list):
                logger.info(f"[KB] 检测到旧格式 registry (list), 迁移到新格式...")
                kbs = {}
                for name in raw:
                    if os.path.isdir(os.path.join(KB_ROOT, name)):
                        kbs[name] = {
                            "path": os.path.join(KB_ROOT, name),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                data = {"kbs": kbs, "current": next(iter(kbs.keys())) if kbs else None}
                # 立即保存新格式
                with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"[KB] 迁移完成: {len(kbs)} 个知识库")
                return data

            # ── 新格式校验 ──
            if not isinstance(raw, dict) or "kbs" not in raw:
                logger.warning(f"[KB] registry 格式异常, 重置")
                return {"kbs": {}, "current": None}
            if "current" not in raw:
                raw["current"] = None
            return raw

        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"Failed to load registry, starting fresh: {exc}")
            return {"kbs": {}, "current": None}

    def _save_registry(self) -> None:
        """Persist registry back to disk."""
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(self._registry, f, ensure_ascii=False, indent=2)

    def list_knowledge_bases(self) -> list[str]:
        """Return list of all registered KB names."""
        return list(self._registry.get("kbs", {}).keys())

    def get_current_kb_name(self) -> Optional[str]:
        """Return the name of the currently active KB, or None."""
        return self._registry.get("current")

    def set_current_kb(self, name: str) -> None:
        """Switch the current KB (must exist)."""
        if name not in self._registry.get("kbs", {}):
            raise ValueError(f"Knowledge base '{name}' does not exist")
        self._registry["current"] = name
        self._save_registry()
        logger.info(f"Switched current KB to '{name}'")

    def get_kb_path(self, name: str) -> str:
        """Return the filesystem path for a KB."""
        return os.path.join(KB_ROOT, name)

    def kb_exists(self, name: str) -> bool:
        """Check whether a KB is registered."""
        return name in self._registry.get("kbs", {})

    # ------------------------------------------------------------------
    # KB lifecycle
    # ------------------------------------------------------------------

    def create_knowledge_base(self, name: str) -> bool:
        """Create a new knowledge base with directory structure and registry entry.

        Returns False if the KB already exists.
        """
        if self.kb_exists(name):
            logger.warning(f"Knowledge base '{name}' already exists, skipping")
            return False

        kb_path = self.get_kb_path(name)
        os.makedirs(os.path.join(kb_path, "content"), exist_ok=True)
        os.makedirs(os.path.join(kb_path, "chroma_db"), exist_ok=True)

        self._registry.setdefault("kbs", {})[name] = {
            "path": kb_path,
            "created_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        }
        self._save_registry()

        # Initialise KBStore (creates info.db and tables)
        store = KBStore(kb_path)
        self._stores[name] = store

        logger.info(f"Knowledge base '{name}' created at {kb_path}")
        return True

    def delete_knowledge_base(self, name: str) -> bool:
        """Delete a knowledge base: directory, registry entry, and caches.

        Not allowed on the current KB — switch first.
        Returns False if the KB doesn't exist.
        """
        if not self.kb_exists(name):
            logger.warning(f"Knowledge base '{name}' does not exist, nothing to delete")
            return False

        if self._registry.get("current") == name:
            logger.error(
                f"Cannot delete currently active KB '{name}'. "
                "Switch to another KB first."
            )
            return False

        kb_path = self.get_kb_path(name)

        # Close and discard cached store
        if name in self._stores:
            try:
                self._stores[name].close()
            except Exception:
                pass
            del self._stores[name]

        # Discard vector store cache
        self._vector_stores.pop(name, None)

        # Remove directory tree
        if os.path.isdir(kb_path):
            shutil.rmtree(kb_path)
            logger.debug(f"Removed directory: {kb_path}")

        # Remove registry entry
        del self._registry["kbs"][name]
        self._save_registry()

        logger.info(f"Knowledge base '{name}' deleted")
        return True

    # ------------------------------------------------------------------
    # per-KB lazy accessors
    # ------------------------------------------------------------------

    def _ensure_store(self, name: str) -> KBStore:
        """Return cached or newly created KBStore for *name*."""
        if name not in self._stores:
            kb_path = self.get_kb_path(name)
            self._stores[name] = KBStore(kb_path)
        return self._stores[name]

    def _ensure_vector_store(self, name: str):
        """Return cached or newly created VectorStoreService for *name*."""
        if name not in self._vector_stores:
            from kb.vector_store import VectorStoreService  # lazy import

            kb_path = self.get_kb_path(name)
            self._vector_stores[name] = VectorStoreService(kb_path)
        return self._vector_stores[name]

    def get_store(self, name: Optional[str] = None) -> KBStore:
        """Get KBStore for *name*, falling back to the current KB."""
        name = name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )
        return self._ensure_store(name)

    def get_vector_store(self, name: Optional[str] = None):
        """Get VectorStoreService for *name*, falling back to the current KB."""
        name = name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )
        return self._ensure_vector_store(name)

    def get_retriever(self, name: Optional[str] = None):
        """Shortcut: get fusion retriever for the given (or current) KB."""
        return self.get_vector_store(name).get_fusion_retriever()

    # ------------------------------------------------------------------
    # document operations (delegate to current / named KB)
    # ------------------------------------------------------------------

    def upload_document(
        self,
        file_obj,
        filename: str,
        kb_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload a document to the KB.

        Steps:
          1. Save the file under ``{kb_path}/content/{filename}``
          2. Compute MD5
          3. Register in KBStore
          4. Auto-vectorize via VectorStoreService

        Returns the full document dict from KBStore.
        """
        name = kb_name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )

        store = self.get_store(name)
        kb_path = self.get_kb_path(name)
        content_dir = os.path.join(kb_path, "content")
        os.makedirs(content_dir, exist_ok=True)

        dest_path = os.path.join(content_dir, filename)

        # Write file bytes
        raw = file_obj.read() if hasattr(file_obj, "read") else file_obj
        with open(dest_path, "wb") as f:
            f.write(raw)

        md5_hex = _get_file_md5_hex(dest_path)
        file_size = os.path.getsize(dest_path)
        _, ext = os.path.splitext(filename)

        doc_id = store.add_document(
            file_name=filename,
            file_path=dest_path,
            md5=md5_hex,
            file_size=file_size,
            file_type=ext.lstrip(".").lower(),
        )

        # Auto-vectorize
        try:
            vs = self._ensure_vector_store(name)
            vs.load_single_document(dest_path)
            store.update_status(doc_id, "vectorized")
            logger.info(
                f"Document '{filename}' (id={doc_id}) uploaded and "
                f"vectorized in KB '{name}'"
            )
        except Exception as exc:
            logger.warning(
                f"Document '{filename}' uploaded but auto-vectorize "
                f"failed (id={doc_id}): {exc}"
            )

        result = store.get_document(doc_id)
        return result if result is not None else {}

    def list_documents(
        self,
        kb_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return all documents for the given (or current) KB."""
        name = kb_name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )
        return self.get_store(name).list_documents()

    def delete_document(
        self,
        doc_id: int,
        kb_name: Optional[str] = None,
    ) -> bool:
        """Delete a document and all its associated data.

        Steps:
          1. Get document metadata from KBStore
          2. Delete vectors from ChromaDB by source path
          3. Delete BM25 tokens by chunk IDs
          4. Delete the content file
          5. Remove the KBStore record
        """
        name = kb_name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )

        store = self.get_store(name)
        doc = store.get_document(doc_id)
        if doc is None:
            logger.warning(
                f"Document id={doc_id} not found in KB '{name}'"
            )
            return False

        file_path: str = doc["file_path"]
        file_name: str = doc["file_name"]

        # --- collect chunk IDs (for BM25 cleanup) and delete from ChromaDB ---
        chunk_ids: list[str] = []
        try:
            vs = self._ensure_vector_store(name)
            result = vs.vector_store.get(where={"source": {"$eq": file_path}})
            chunk_ids = result.get("ids", [])
            vs.vector_store._collection.delete(
                where={"source": {"$eq": file_path}}
            )
            logger.debug(
                f"Deleted {len(chunk_ids)} ChromaDB vectors for "
                f"'{file_path}'"
            )
        except Exception as exc:
            logger.warning(
                f"Failed to delete vectors from ChromaDB: {exc}"
            )

        # --- BM25 token cleanup ---
        if chunk_ids:
            try:
                store.delete_bm25_tokens_by_chunk_ids(chunk_ids)
            except Exception as exc:
                logger.warning(
                    f"Failed to delete BM25 tokens: {exc}"
                )

        # --- delete content file ---
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Deleted content file: {file_path}")
            except OSError as exc:
                logger.warning(
                    f"Failed to delete content file '{file_path}': {exc}"
                )

        # --- remove KBStore record ---
        store.delete_document(doc_id)

        logger.info(
            f"Document '{file_name}' (id={doc_id}) deleted from KB "
            f"'{name}'"
        )
        return True

    def revectorize_document(
        self,
        doc_id: int,
        kb_name: Optional[str] = None,
    ) -> bool:
        """Re-chunk and re-vectorize a document in-place.

        Steps:
          1. Get document from KBStore
          2. Load + chunk the original file
          3. Compute new MD5
          4. Clear old ChromaDB vectors
          5. Write new vectors
          6. Update BM25 tokens (delete old, save new)
          7. Update status / MD5 / chunk_count in KBStore
        """
        name = kb_name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )

        store = self.get_store(name)
        doc = store.get_document(doc_id)
        if doc is None:
            logger.warning(
                f"Document id={doc_id} not found in KB '{name}'"
            )
            return False

        file_path: str = doc["file_path"]
        file_name: str = doc["file_name"]

        if not os.path.isfile(file_path):
            logger.error(
                f"File not found for document '{file_name}' "
                f"(id={doc_id}): {file_path}"
            )
            return False

        # --- load + chunk ---
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            from utils.config_handler import chroma_conf
            from utils.file_handler import docling_loader

            documents = docling_loader(file_path)
            if not documents:
                logger.warning(f"No content loaded from '{file_path}'")
                return False

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chroma_conf.get("chunk_size", 200),
                chunk_overlap=chroma_conf.get("chunk_overlap", 30),
                separators=chroma_conf.get(
                    "separators",
                    ["\n\n", "\n", ".", "!", "?", "。", "！", "？", " ", ""],
                ),
                length_function=len,
            )
            chunks = splitter.split_documents(documents)
            if not chunks:
                logger.warning(
                    f"No chunks after splitting '{file_path}'"
                )
                return False
        except Exception as exc:
            logger.error(
                f"Failed to load / chunk '{file_path}': {exc}",
                exc_info=True,
            )
            return False

        # --- recompute MD5 ---
        md5_hex = _get_file_md5_hex(file_path)

        # --- inject metadata into chunks ---
        for i, chunk in enumerate(chunks):
            chunk.metadata["source"] = file_path
            chunk.metadata["file_md5"] = md5_hex
            chunk.metadata["chunk_index"] = i

        vs = self._ensure_vector_store(name)

        # --- collect old chunk IDs ---
        old_chunk_ids: list[str] = []
        try:
            result = vs.vector_store.get(
                where={"source": {"$eq": file_path}}
            )
            old_chunk_ids = result.get("ids", [])
        except Exception:
            pass

        # --- clear old vectors ---
        try:
            vs.vector_store._collection.delete(
                where={"source": {"$eq": file_path}}
            )
        except Exception as exc:
            logger.warning(
                f"Failed to clear old vectors for '{file_path}': {exc}"
            )

        # --- write new vectors (capture auto-generated IDs) ---
        new_ids: list[str] = []
        try:
            new_ids = vs.vector_store.add_documents(chunks)
        except Exception as exc:
            logger.error(
                f"Failed to write new vectors for '{file_path}': {exc}",
                exc_info=True,
            )
            return False

        # --- update BM25 tokens ---
        if old_chunk_ids:
            try:
                store.delete_bm25_tokens_by_chunk_ids(old_chunk_ids)
            except Exception as exc:
                logger.warning(
                    f"Failed to delete old BM25 tokens: {exc}"
                )

        if new_ids:
            try:
                import jieba

                for i, chunk in enumerate(chunks):
                    if i >= len(new_ids):
                        break
                    tokens = " ".join(jieba.cut(chunk.page_content))
                    store.save_bm25_tokens(
                        chunk_id=new_ids[i],
                        tokens=tokens,
                        doc_length=len(tokens.split()),
                        doc_preview=chunk.page_content[:100],
                    )
            except ImportError:
                logger.debug(
                    "jieba not available — skipping BM25 token cache update"
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to save BM25 tokens: {exc}"
                )

        # --- update store metadata ---
        store.update_md5(doc_id, md5_hex)
        store.update_status(doc_id, "vectorized", chunk_count=len(chunks))

        logger.info(
            f"Document '{file_name}' (id={doc_id}) revectorized "
            f"({len(chunks)} chunks) in KB '{name}'"
        )
        return True

    def download_document(
        self,
        doc_id: int,
        kb_name: Optional[str] = None,
    ) -> tuple[bytes, str]:
        """Return ``(file_bytes, filename)`` for download."""
        name = kb_name or self.get_current_kb_name()
        if name is None:
            raise ValueError(
                "No knowledge base specified and none is currently active"
            )

        store = self.get_store(name)
        doc = store.get_document(doc_id)
        if doc is None:
            raise ValueError(
                f"Document id={doc_id} not found in KB '{name}'"
            )

        file_path: str = doc["file_path"]
        if not os.path.isfile(file_path):
            raise FileNotFoundError(
                f"File not found for document '{doc['file_name']}' "
                f"(id={doc_id}): {file_path}"
            )

        with open(file_path, "rb") as f:
            content = f.read()

        return content, doc["file_name"]


# ------------------------------------------------------------------
# module-level singleton
# ------------------------------------------------------------------

kb_manager: Optional[KBManager] = None


def init_kb_manager() -> KBManager:
    """Return the module-level KBManager singleton, creating it if needed."""
    global kb_manager
    if kb_manager is None:
        kb_manager = KBManager()
    return kb_manager
