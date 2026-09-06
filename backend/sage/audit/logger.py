import structlog
import logging
import json
from datetime import datetime, timezone
from sage.config import settings
from sage.core.utils import configure_stdio_encoding
from typing import Any

configure_stdio_encoding()

# Configure standard logging to use structlog
logging.basicConfig(level=settings.LOG_LEVEL.upper(), format="%(message)s")

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger("sage.audit")

class AuditLogger:
    @staticmethod
    def log_event(event_type: str, user_id: str | None, session_id: str | None, data: dict[str, Any]):
        """Logs an event as structured JSON."""
        logger.info(
            event_type,
            user_id=user_id,
            session_id=session_id,
            data=data
        )
        
        # In Phase 1+, we will also insert this into the PostgreSQL audit_logs table
        # via an async background task or direct DB session.

    @staticmethod
    def log_request(method: str, path: str, status_code: int, user_id: str | None = None, latency_ms: float = 0.0):
        logger.info(
            "api_request",
            method=method,
            path=path,
            status_code=status_code,
            user_id=user_id,
            latency_ms=latency_ms
        )

    @staticmethod
    def log_sandbox_execution(
        user_id: str | None,
        session_id: str | None,
        sandbox_id: str,
        language: str,
        code_hash: str,
        exit_code: int,
        duration_ms: float,
        files_created: list[str] | None = None,
    ):
        """Log a sandbox code execution event."""
        logger.info(
            "sandbox_execution",
            user_id=user_id,
            session_id=session_id,
            data={
                "sandbox_id": sandbox_id,
                "language": language,
                "code_hash": code_hash,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "files_created": files_created or [],
            },
        )

    @staticmethod
    def log_file_upload(
        user_id: str | None,
        session_id: str | None,
        filename: str,
        size_bytes: int,
        mime_type: str,
        saved_path: str,
    ):
        """Log a file upload event."""
        logger.info(
            "file_upload",
            user_id=user_id,
            session_id=session_id,
            data={
                "filename": filename,
                "size_bytes": size_bytes,
                "mime_type": mime_type,
                "saved_path": saved_path,
            },
        )
