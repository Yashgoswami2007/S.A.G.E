import os
import shutil
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sage.rag.chunker import DocumentChunker
from sage.rag.embedder import LocalEmbedder
from sage.rag.vector_store import get_vector_store
from sage.rag.retriever import HybridRetriever
from sage.config import settings

router = APIRouter()

# Shared RAG instance for API requests
def _get_api_retriever() -> HybridRetriever:
    vector_db_path = os.path.join(settings.WORKSPACE_DIR, "vector_db")
    store = get_vector_store(vector_db_path)
    embedder = LocalEmbedder()
    return HybridRetriever(vector_store=store, embedder=embedder)

class SearchRequest(BaseModel):
    query: str
    collection: Optional[str] = "default"
    top_k: Optional[int] = 4

class IngestPathRequest(BaseModel):
    path: str
    collection: Optional[str] = "default"

@router.post("/search")
async def search_knowledge_base(req: SearchRequest):
    """Direct semantic & hybrid search against the sovereign knowledge base."""
    retriever = _get_api_retriever()
    results = retriever.search(
        query=req.query,
        collection=req.collection,
        top_k=req.top_k or 4
    )
    citations_text = retriever.format_citations(results)
    return {
        "query": req.query,
        "collection": req.collection,
        "results_count": len(results),
        "citations": citations_text,
        "raw_results": results
    }

@router.post("/ingest-file")
async def ingest_uploaded_file(
    file: UploadFile = File(...),
    collection: str = Form("default")
):
    """Uploads and indexes a document (PDF, DOCX, TXT) into the vector store."""
    upload_dir = os.path.join(settings.WORKSPACE_DIR, "knowledge_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    chunker = DocumentChunker()
    chunks = chunker.chunk_file(file_path)
    if not chunks:
        raise HTTPException(status_code=400, detail="Could not extract readable text from uploaded file.")

    retriever = _get_api_retriever()
    texts = [c["text"] for c in chunks]
    embeddings = retriever.embedder.embed_batch(texts)
    added = retriever.vector_store.add_documents(chunks, embeddings, collection=collection)

    return {
        "status": "success",
        "filename": file.filename,
        "collection": collection,
        "chunks_indexed": added
    }

@router.post("/ingest-path")
async def ingest_path(req: IngestPathRequest):
    """Indexes an existing document inside the workspace."""
    target_path = req.path
    if not os.path.isabs(target_path):
        target_path = os.path.join(settings.WORKSPACE_DIR, target_path)

    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.path}")

    chunker = DocumentChunker()
    chunks = chunker.chunk_file(target_path)
    if not chunks:
        raise HTTPException(status_code=400, detail="No readable content found in file.")

    retriever = _get_api_retriever()
    texts = [c["text"] for c in chunks]
    embeddings = retriever.embedder.embed_batch(texts)
    added = retriever.vector_store.add_documents(chunks, embeddings, collection=req.collection or "default")

    return {
        "status": "success",
        "file": req.path,
        "collection": req.collection,
        "chunks_indexed": added
    }

@router.get("/stats")
async def get_rag_stats():
    """Returns total chunk counts and active collections."""
    retriever = _get_api_retriever()
    return retriever.vector_store.get_stats()

@router.delete("/collections/{collection_name}")
async def delete_collection(collection_name: str):
    """Deletes all indexed chunks for a collection."""
    retriever = _get_api_retriever()
    success = retriever.vector_store.delete_collection(collection_name)
    return {"status": "success" if success else "not_found", "collection": collection_name}
