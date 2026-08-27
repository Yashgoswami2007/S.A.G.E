import hashlib
import uuid
from datetime import datetime, timezone

def utc_now() -> datetime:
    """Returns a timezone-aware datetime object for the current time in UTC."""
    return datetime.now(timezone.utc)

def hash_content(data: bytes) -> str:
    """Returns the SHA-256 hex digest of the given data."""
    return hashlib.sha256(data).hexdigest()

def generate_id() -> str:
    """Generates a UUID4 string."""
    return str(uuid.uuid4())
