from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sage.core.utils import generate_id, utc_now

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_id)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(String, primary_key=True, default=generate_id)
    timestamp = Column(DateTime(timezone=True), default=utc_now, index=True)
    event_type = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)
    session_id = Column(String, index=True, nullable=True)
    data_json = Column(JSON, nullable=False)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(String, primary_key=True, default=generate_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    profile = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, default=generate_id)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False) # user, assistant, system, tool
    content = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    
    session = relationship("ChatSession", back_populates="messages")

from sage.rag.models import RagDocument, RagChunk  # noqa: F401
