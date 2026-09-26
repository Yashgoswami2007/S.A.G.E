from sqlalchemy import Column, String, Integer, DateTime, Text, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from sage.db.models import Base
from sage.core.utils import generate_id, utc_now

class RagDocument(Base):
    __tablename__ = "rag_documents"

    id           = Column(String, primary_key=True, default=generate_id)
    workspace_id = Column(String, nullable=False, index=True)
    filename     = Column(String, nullable=False)
    file_path    = Column(String, nullable=False)
    file_type    = Column(String, nullable=False)              # pdf, docx, xlsx, pptx, txt, md
    file_hash    = Column(String, nullable=False)              # SHA-256 of raw file bytes
    file_size    = Column(Integer, nullable=False)
    page_count   = Column(Integer, default=0)
    chunk_count  = Column(Integer, default=0)
    status       = Column(String, default="pending")           # pending, indexing, indexed, failed
    error        = Column(Text, nullable=True)
    metadata_    = Column("metadata", JSONB, default=dict)
    created_at   = Column(DateTime(timezone=True), default=utc_now)
    updated_at   = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_rag_doc_workspace_hash", "workspace_id", "file_hash", unique=True),
    )

class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id            = Column(String, primary_key=True, default=generate_id)
    document_id   = Column(String, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False)
    workspace_id  = Column(String, nullable=False, index=True)
    chunk_index   = Column(Integer, nullable=False)
    content       = Column(Text, nullable=False)
    content_hash  = Column(String, nullable=False)
    page_number   = Column(Integer, nullable=True)
    section       = Column(String, nullable=True)
    char_offset   = Column(Integer, default=0)
    token_count   = Column(Integer, default=0)
    embedding     = Column(Vector(384), nullable=True)         # dimension matches model
    metadata_     = Column("metadata", JSONB, default=dict)
    created_at    = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_rag_chunk_doc", "document_id"),
        Index("ix_rag_chunk_workspace", "workspace_id"),
    )
