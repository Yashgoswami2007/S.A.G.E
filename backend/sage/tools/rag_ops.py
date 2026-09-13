import os
from typing import Optional
from sage.tools.base import BaseTool, ToolResult, ToolPermission
from sage.rag.chunker import DocumentChunker
from sage.rag.embedder import LocalEmbedder
from sage.rag.vector_store import get_vector_store
from sage.rag.retriever import HybridRetriever
from sage.config import settings

# Lazy singletons for RAG operations
_retriever: Optional[HybridRetriever] = None
_chunker = DocumentChunker()

def _get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        vector_db_path = os.path.join(settings.WORKSPACE_DIR, "vector_db")
        store = get_vector_store(vector_db_path)
        embedder = LocalEmbedder()
        _retriever = HybridRetriever(vector_store=store, embedder=embedder)
    return _retriever


class RagSearchTool(BaseTool):
    name = "rag_search"
    description = (
        "Search the sovereign on-premise knowledge base and standard operating procedures (SOPs). "
        "Use this tool whenever you need factual refinery standards, safety thresholds, equipment manuals, or operating limits."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Specific search query, equipment code (e.g. HEX-401), or procedure keyword."
            },
            "collection": {
                "type": "string",
                "description": "Optional collection name (defaults to 'default')."
            },
            "top_k": {
                "type": "integer",
                "description": "Number of relevant chunks to retrieve (defaults to 4)."
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, collection: str = "default", top_k: int = 4, **kwargs) -> ToolResult:
        try:
            retriever = _get_retriever()
            results = retriever.search(query=query, collection=collection, top_k=top_k)
            if not results:
                # Also try search without collection filter if specific collection yields nothing
                if collection != "default":
                    results = retriever.search(query=query, collection=None, top_k=top_k)

            if not results:
                return ToolResult(
                    success=True,
                    output="No matching standard operating procedures or documentation found in the knowledge base."
                )

            formatted_text = retriever.format_citations(results)
            return ToolResult(
                success=True,
                output=formatted_text,
                data={"result_count": len(results), "top_score": results[0].get("hybrid_score", 0.0)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"RAG search execution failed: {str(e)}"
            )


class RagIngestTool(BaseTool):
    name = "rag_ingest"
    description = (
        "Ingest and index a local document (PDF, DOCX, or text file) into the sovereign knowledge base "
        "so the agent can semantically search and cite it."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the document file to index."
            },
            "collection": {
                "type": "string",
                "description": "Collection name to group these documents into (e.g. 'sops', 'inspections')."
            }
        },
        "required": ["path"]
    }

    async def execute(self, path: str, collection: str = "default", **kwargs) -> ToolResult:
        try:
            # Resolve path within workspace if relative
            target_path = path
            if not os.path.isabs(target_path):
                target_path = os.path.join(settings.WORKSPACE_DIR, path)

            if not os.path.exists(target_path):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found for ingestion: {path}"
                )

            chunks = _chunker.chunk_file(target_path)
            if not chunks:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Document could not be parsed or contains no readable text: {path}"
                )

            retriever = _get_retriever()
            texts = [c["text"] for c in chunks]
            embeddings = retriever.embedder.embed_batch(texts)
            added_count = retriever.vector_store.add_documents(
                chunks=chunks,
                embeddings=embeddings,
                collection=collection
            )

            return ToolResult(
                success=True,
                output=f"Successfully indexed '{os.path.basename(path)}' ({added_count} chunks stored in collection '{collection}').",
                data={"chunks_indexed": added_count, "collection": collection, "file": path}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"RAG document ingestion failed: {str(e)}"
            )
