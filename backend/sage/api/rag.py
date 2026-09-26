"""
SAGE RAG (Knowledge Base) API — manages document indexing, listing, deletion, and search.

Endpoints:
  POST   /upload        — Upload files directly into the knowledge base
  POST   /index         — Index an existing workspace file by path
  GET    /documents     — List all indexed documents for the active workspace
  GET    /documents/:id — Get a single document's details
  DELETE /documents/:id — Remove a document and its chunks
  GET    /status        — Check the indexing queue status
  POST   /search        — Semantic search across indexed documents
"""

import logging
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import hashlib
import aiofiles

import sage.workspace as _ws_module
from sage.db.session import AsyncSessionLocal
from sage.rag.store import VectorStore
from sage.rag.models import RagDocument
from sage.rag.queue import indexing_queue, IndexingJob
from sage.rag.ingest import _FILE_TYPE_MAP, _hash_file

logger = logging.getLogger("sage.api.rag")

router = APIRouter()
store = VectorStore()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _serialize_document(doc: RagDocument) -> dict:
    """Convert a SQLAlchemy RagDocument to a JSON-serializable dict."""
    return {
        "id": doc.id,
        "workspace_id": doc.workspace_id,
        "filename": doc.filename,
        "file_path": doc.file_path,
        "file_type": doc.file_type,
        "file_hash": doc.file_hash,
        "file_size": doc.file_size,
        "page_count": doc.page_count or 0,
        "chunk_count": doc.chunk_count or 0,
        "status": doc.status,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def detect_file_type(file_path: str) -> str:
    path = Path(file_path)
    return _FILE_TYPE_MAP.get(path.suffix.lower(), "txt")


def hash_file(file_path: str) -> str:
    return _hash_file(file_path)


def get_active_workspace_id() -> str:
    workspace = _ws_module.workspace_manager.get_active_workspace()
    return hashlib.sha256(workspace.encode()).hexdigest()[:16]


def _get_workspace_path() -> Path:
    return Path(_ws_module.workspace_manager.get_active_workspace()).resolve()


# ── Request Schemas ──────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    file_path: str
    workspace_id: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    workspace_id: Optional[str] = None
    top_k: int = 5


# ── Upload Endpoint ──────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_to_knowledge_base(
    files: List[UploadFile] = File(...),
) -> dict:
    """
    Upload files directly into the Knowledge Base.
    Saves them to workspace/uploads/knowledge/ and enqueues for RAG indexing.
    """
    workspace = _get_workspace_path()
    upload_dir = workspace / "uploads" / "knowledge"
    upload_dir.mkdir(parents=True, exist_ok=True)

    ws_id = get_active_workspace_id()
    uploaded = []
    errors = []

    for file in files:
        original_name = file.filename or "unnamed_file"
        safe_name = _sanitize_filename(original_name)
        dest = upload_dir / safe_name

        # Deduplicate filenames
        counter = 1
        stem = dest.stem
        while dest.exists():
            dest = upload_dir / f"{stem}_{counter}{dest.suffix}"
            counter += 1

        try:
            content = await file.read()
            async with aiofiles.open(dest, "wb") as f:
                await f.write(content)

            file_hash = hash_file(str(dest))
            file_type = detect_file_type(str(dest))

            async with AsyncSessionLocal() as db:
                # Check for duplicate
                existing = await store.get_document_by_hash(db, ws_id, file_hash)
                if existing:
                    uploaded.append(_serialize_document(existing))
                    continue

                doc = RagDocument(
                    workspace_id=ws_id,
                    filename=original_name,
                    file_path=str(dest),
                    file_type=file_type,
                    file_hash=file_hash,
                    file_size=len(content),
                    status="pending",
                )
                await store.insert_document(db, doc)

                # Enqueue for indexing
                if indexing_queue:
                    indexing_queue.enqueue(IndexingJob(
                        file_path=str(dest),
                        workspace_id=ws_id,
                        document_id=doc.id,
                    ))

                uploaded.append(_serialize_document(doc))
                logger.info("Knowledge base upload: %s (%d bytes) -> %s", original_name, len(content), dest)

        except Exception as e:
            errors.append({"filename": original_name, "error": str(e)})
            logger.error("Failed to upload %s to knowledge base: %s", original_name, e)

    if not uploaded and errors:
        raise HTTPException(status_code=400, detail=f"All uploads failed: {errors}")

    return {"documents": uploaded, "errors": errors}


def _sanitize_filename(filename: str) -> str:
    import re
    name = filename.replace("/", "_").replace("\\", "_").replace("\0", "")
    name = name.lstrip(".")
    name = re.sub(r'[^\w\s\-.]', '_', name)
    name = re.sub(r'[_\s]+', '_', name).strip("_")
    return name or "unnamed_file"


# ── Index (by path) ─────────────────────────────────────────────────────────

@router.post("/index")
async def index_file(req: IndexRequest):
    if indexing_queue is None:
        raise HTTPException(503, "RAG indexing service not running")

    if not Path(req.file_path).exists():
        raise HTTPException(404, "File not found")

    ws_id = req.workspace_id or get_active_workspace_id()

    async with AsyncSessionLocal() as db:
        file_hash = hash_file(req.file_path)
        existing = await store.get_document_by_hash(db, ws_id, file_hash)
        if existing:
            return {"status": "exists", "document": _serialize_document(existing)}

        doc = RagDocument(
            workspace_id=ws_id,
            filename=Path(req.file_path).name,
            file_path=req.file_path,
            file_type=detect_file_type(req.file_path),
            file_hash=file_hash,
            file_size=Path(req.file_path).stat().st_size,
            status="pending",
        )
        await store.insert_document(db, doc)

    success = indexing_queue.enqueue(IndexingJob(
        file_path=req.file_path,
        workspace_id=ws_id,
        document_id=doc.id,
    ))

    if not success:
        return {"status": "rejected", "reason": "Queue full. Try again later."}

    return {"status": "queued", "document": _serialize_document(doc)}


# ── List / Get / Delete ──────────────────────────────────────────────────────

@router.get("/documents")
async def list_documents(workspace_id: Optional[str] = None):
    ws_id = workspace_id or get_active_workspace_id()
    async with AsyncSessionLocal() as db:
        docs = await store.list_documents(db, ws_id)
        return [_serialize_document(d) for d in docs]


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    async with AsyncSessionLocal() as db:
        doc = await store.get_document(db, doc_id)
        if not doc:
            raise HTTPException(404, "Document not found")
        return _serialize_document(doc)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    async with AsyncSessionLocal() as db:
        success = await store.delete_document(db, doc_id)
        if not success:
            raise HTTPException(404, "Document not found")
        return {"status": "deleted"}


# ── Queue Status ─────────────────────────────────────────────────────────────

@router.get("/status")
async def get_queue_status():
    if indexing_queue is None:
        return {"status": "not_running"}
    return {"status": "running", "pending_count": indexing_queue.pending_count}


# ── Semantic Search ──────────────────────────────────────────────────────────

@router.post("/search")
async def search(req: SearchRequest):
    from sage.rag.retriever import Retriever
    from sage.rag.citations import format_citations
    ws_id = req.workspace_id or get_active_workspace_id()
    async with AsyncSessionLocal() as db:
        retriever = Retriever(store)
        results = await retriever.retrieve(db, req.query, ws_id, req.top_k)

        if not results:
            return {"context": "", "chunks_retrieved": 0, "results": []}

        context = format_citations(results)
        return {
            "context": context,
            "chunks_retrieved": len(results),
            "results": [
                {
                    "content": r.content,
                    "score": r.score,
                    "document_filename": r.document_filename,
                    "page_number": r.page_number,
                    "section": r.section
                } for r in results
            ]
        }
