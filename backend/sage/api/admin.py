from fastapi import APIRouter, Request
from sage.models.registry import ModelRegistry
from sage.config import settings

router = APIRouter()

@router.get("/models")
async def list_models(request: Request):
    """List all registered models (Admin only)."""
    # request.state.user contains user info from AuthMiddleware
    registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
    return {"models": [m.model_dump() for m in registry.list_all()]}
