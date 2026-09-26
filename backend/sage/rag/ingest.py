import hashlib
import os
import logging
from pathlib import Path
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sage.config import settings
from sage.rag.models import RagDocument, RagChunk
from sage.rag.chunker import DocumentChunker
from sage.rag.store import VectorStore
from sage.models.embedding_client import EmbeddingClient

logger = logging.getLogger("sage.rag.ingest")

_FILE_TYPE_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "md",
}

def _hash_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

class IngestionPipeline:
    def __init__(self, chunker: DocumentChunker, store: VectorStore):
        self.chunker = chunker
        self.store = store

    @classmethod
    def create_default(cls) -> "IngestionPipeline":
        chunker = DocumentChunker(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP
        )
        return cls(chunker, VectorStore())

    def _get_lifecycle_manager(self):
        from sage.agent.dependencies import get_lifecycle_manager
        # this might be async or require app state, let's try to get it from registry
        from sage.api.deps import get_lifecycle_manager as get_lm
        # Actually, get_lm requires a Request. Let's get the global one if possible.
        # It's better to fetch it via the global registry in main.py or just instantiate.
        # Since it's a singleton (usually), we can get it from app.state in FastAPI context, 
        # but here we might not have a Request.
        # We can reconstruct it or retrieve the global instance.
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

    async def ingest_file(self, db: AsyncSession, file_path: str, workspace_id: str, document_id: str = None) -> RagDocument:
        """
        Full pipeline for one file.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"{file_path} not found")

        file_hash = _hash_file(file_path)
        
        # Check dedup
        existing = await self.store.get_document_by_hash(db, workspace_id, file_hash)
        if existing and existing.status == "indexed":
            logger.info(f"File {file_path} already indexed for workspace {workspace_id}")
            return existing

        file_type = _FILE_TYPE_MAP.get(path.suffix.lower(), "txt")
        file_size = path.stat().st_size

        if document_id:
            doc = await self.store.get_document(db, document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")
        else:
            doc = RagDocument(
                workspace_id=workspace_id,
                filename=path.name,
                file_path=file_path,
                file_type=file_type,
                file_hash=file_hash,
                file_size=file_size,
                status="indexing"
            )
            await self.store.insert_document(db, doc)

        await self.store.update_document_status(db, doc.id, "indexing")

        # Acquire embedding model
        lifecycle = self._get_lifecycle_manager()
        embed_model_id = settings.RAG_EMBEDDING_MODEL_ID
        if lifecycle:
            ready = await lifecycle.ensure_model(embed_model_id)
            if not ready:
                error_msg = f"Embedding model {embed_model_id} could not be loaded"
                await self.store.update_document_status(db, doc.id, "failed", error=error_msg)
                raise RuntimeError(error_msg)
        
        try:
            # 1. Chunk
            raw_chunks = self.chunker.chunk_file(file_path, file_type)
            if not raw_chunks:
                await self.store.update_document_status(db, doc.id, "indexed")
                return doc
            
            # 2. Embed in batches
            embedding_client = await self._get_embedding_client()
            batch_size = 32
            db_chunks = []
            
            for i in range(0, len(raw_chunks), batch_size):
                batch = raw_chunks[i:i+batch_size]
                texts = [c.content for c in batch]
                
                embeddings = await embedding_client.embed(texts)
                
                for c, emb in zip(batch, embeddings):
                    db_chunks.append(RagChunk(
                        document_id=doc.id,
                        workspace_id=workspace_id,
                        chunk_index=c.chunk_index,
                        content=c.content,
                        content_hash=_hash_text(c.content),
                        page_number=c.page_number,
                        section=c.section,
                        char_offset=c.char_offset,
                        token_count=c.token_count,
                        embedding=emb,
                        metadata_=c.metadata
                    ))
            
            # 3. Store
            await self.store.insert_chunks(db, db_chunks)
            
            # 4. Update status
            doc.status = "indexed"
            doc.chunk_count = len(db_chunks)
            await db.commit()
            return doc
            
        except Exception as e:
            logger.error(f"Ingestion failed for {file_path}: {e}")
            await self.store.update_document_status(db, doc.id, "failed", error=str(e))
            raise
        finally:
            if lifecycle:
                await lifecycle.release_model(embed_model_id)

    async def reindex_file(self, db: AsyncSession, document_id: str) -> RagDocument:
        doc = await self.store.get_document(db, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found")
        
        # Delete existing chunks implicitly by deleting the document?
        # Actually it's easier to just delete the doc and re-create, or delete chunks.
        # Let's delete chunks.
        from sqlalchemy import delete
        await db.execute(delete(RagChunk).where(RagChunk.document_id == document_id))
        await db.commit()
        
        return await self.ingest_file(db, doc.file_path, doc.workspace_id, document_id)
