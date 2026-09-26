import os
from typing import List, Optional
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sage.config import settings
from sage.rag.store import VectorStore
from sage.models.embedding_client import EmbeddingClient

@dataclass
class RetrievedChunk:
    content: str
    score: float
    document_id: str
    document_filename: str
    page_number: Optional[int]
    section: Optional[str]
    chunk_index: int

class Retriever:
    """Query-time retrieval pipeline."""

    def __init__(self, store: VectorStore):
        self.store = store

    def _get_lifecycle_manager(self):
        from sage.main import app
        return getattr(app.state, "lifecycle_manager", None)

    async def _get_embedding_client(self):
        from sage.models.registry import ModelRegistry
        registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
        embed_model = registry.models.get(settings.RAG_EMBEDDING_MODEL_ID)
        if not embed_model:
            raise RuntimeError(f"Embedding model {settings.RAG_EMBEDDING_MODEL_ID} not configured")
        
        return EmbeddingClient(
            base_url=f"http://localhost:{embed_model.server_port}",
            model=embed_model.model_path if os.path.isabs(embed_model.model_path) else embed_model.id,
            dimension=settings.RAG_EMBEDDING_DIM
        )

    async def retrieve(
        self, db: AsyncSession, query: str, workspace_id: str, top_k: int = 5
    ) -> List[RetrievedChunk]:
        """
        1. Embed query -> single vector
        2. pgvector cosine similarity search
        3. Deduplicate and format
        """
        # 1. Acquire embedding model and embed query
        lifecycle = self._get_lifecycle_manager()
        embed_model_id = settings.RAG_EMBEDDING_MODEL_ID
        if lifecycle:
            ready = await lifecycle.ensure_model(embed_model_id)
            if not ready:
                raise RuntimeError(f"Embedding model {embed_model_id} could not be loaded")
        
        try:
            embedding_client = await self._get_embedding_client()
            query_embedding = await embedding_client.embed_single(query)
        finally:
            if lifecycle:
                await lifecycle.release_model(embed_model_id)

        # 2. Search
        raw_results = await self.store.similarity_search(db, query_embedding, workspace_id, limit=top_k)

        # 3. Format and deduplicate
        seen_hashes = set()
        results: List[RetrievedChunk] = []
        
        for r in raw_results:
            chunk = r["chunk"]
            if chunk.content_hash in seen_hashes:
                continue
            seen_hashes.add(chunk.content_hash)
            
            # Simple prompt injection sanitizer
            safe_content = chunk.content.replace("<|im_start|>", "").replace("<|im_end|>", "")
            
            results.append(RetrievedChunk(
                content=safe_content,
                score=r["score"],
                document_id=chunk.document_id,
                document_filename=r["filename"],
                page_number=chunk.page_number,
                section=chunk.section,
                chunk_index=chunk.chunk_index
            ))

        return results
