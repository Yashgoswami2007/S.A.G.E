from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import List, Optional, Dict, Any
from sage.rag.models import RagDocument, RagChunk

class VectorStore:
    """pgvector CRUD operations for RAG chunks."""

    async def insert_document(self, db: AsyncSession, doc: RagDocument) -> str:
        """Insert a document record. Returns doc ID."""
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc.id

    async def insert_chunks(self, db: AsyncSession, chunks: List[RagChunk]) -> int:
        """Batch insert chunks with embeddings. Returns count inserted."""
        if not chunks:
            return 0
        db.add_all(chunks)
        await db.commit()
        return len(chunks)

    async def similarity_search(
        self, db: AsyncSession, query_embedding: List[float],
        workspace_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Cosine similarity search filtered by workspace_id.
        Returns dicts with: chunk content, score, document filename, page, section.
        Uses pgvector's <=> operator (cosine distance).
        """
        # cosine distance is <=>, so cosine similarity is 1 - distance
        stmt = (
            select(RagChunk, RagDocument.filename)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .where(RagChunk.workspace_id == workspace_id)
            .order_by(RagChunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        result = await db.execute(stmt)
        
        results = []
        for chunk, filename in result:
            # We must compute score in Python, or select the distance explicitly
            # Since we just need it for display/sorting, we can recalculate or omit.
            # But let's select distance in the query.
            pass

        # Better query selecting distance:
        stmt = (
            select(RagChunk, RagDocument.filename, RagChunk.embedding.cosine_distance(query_embedding).label("distance"))
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .where(RagChunk.workspace_id == workspace_id)
            .order_by("distance")
            .limit(limit)
        )
        result = await db.execute(stmt)

        for chunk, filename, distance in result:
            results.append({
                "chunk": chunk,
                "filename": filename,
                "score": 1.0 - (distance or 0.0), # Convert distance to similarity
            })

        return results

    async def get_document(self, db: AsyncSession, doc_id: str) -> Optional[RagDocument]:
        result = await db.execute(select(RagDocument).where(RagDocument.id == doc_id))
        return result.scalar_one_or_none()

    async def list_documents(self, db: AsyncSession, workspace_id: str) -> List[RagDocument]:
        result = await db.execute(select(RagDocument).where(RagDocument.workspace_id == workspace_id).order_by(RagDocument.created_at.desc()))
        return list(result.scalars().all())

    async def delete_document(self, db: AsyncSession, doc_id: str) -> bool:
        """Deletes document + cascades to chunks (via FK ondelete=CASCADE)."""
        result = await db.execute(delete(RagDocument).where(RagDocument.id == doc_id))
        await db.commit()
        return result.rowcount > 0

    async def get_document_by_hash(self, db: AsyncSession, workspace_id: str, file_hash: str) -> Optional[RagDocument]:
        """For dedup: check if this exact file is already indexed."""
        stmt = select(RagDocument).where(
            RagDocument.workspace_id == workspace_id,
            RagDocument.file_hash == file_hash
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_document_status(self, db: AsyncSession, doc_id: str, status: str, error: Optional[str] = None):
        doc = await self.get_document(db, doc_id)
        if doc:
            doc.status = status
            if error is not None:
                doc.error = error
            await db.commit()
