import hashlib
import logging
import os
import sys
import uuid
from datetime import datetime, timezone


def configure_stdio_encoding() -> None:
    """Force UTF-8 on stdio streams (Windows defaults to cp1252 and breaks emoji/unicode)."""
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    for handler in logging.root.handlers:
        stream = getattr(handler, "stream", None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

def utc_now() -> datetime:
    """Returns a timezone-aware datetime object for the current time in UTC."""
    return datetime.now(timezone.utc)

def hash_content(data: bytes) -> str:
    """Returns the SHA-256 hex digest of the given data."""
    return hashlib.sha256(data).hexdigest()

def generate_id() -> str:
    """Generates a UUID4 string."""
    return str(uuid.uuid4())
