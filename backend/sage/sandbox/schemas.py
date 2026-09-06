from pydantic import BaseModel
from typing import List


class SandboxResult(BaseModel):
    """Result of a sandbox code execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    sandbox_id: str          # Unique ID for this execution
    files_created: List[str] = []  # Files created during execution
