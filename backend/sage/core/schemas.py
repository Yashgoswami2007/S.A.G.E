from pydantic import BaseModel
from typing import Any

class HealthResponse(BaseModel):
    status: str
    services: dict[str, str]
    models: list[dict[str, Any]]
    gpu: dict[str, Any] | None = None

class ErrorResponse(BaseModel):
    error: str
    message: str

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserInfo(BaseModel):
    sub: str  # User ID
    role: str
