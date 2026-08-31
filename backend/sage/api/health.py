from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sage.db.session import get_db
from sage.core.schemas import HealthResponse
from sage.config import settings
from sage.models.registry import ModelRegistry
from sage.models.health import check_model_health
from sage.models.gpu_detector import detect_gpus
import httpx

router = APIRouter()

@router.get("", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Returns system health status."""
    services = {"backend": "ok"}
    
    # Check DB
    try:
        await db.execute(text("SELECT 1"))
        services["postgres"] = "ok"
    except Exception as e:
        services["postgres"] = f"error: {str(e)}"
        
    # Check Redis
    try:
        # We don't have a global redis client yet in Phase 0, but we can do a simple check
        import redis.asyncio as redis
        r = redis.from_url(settings.REDIS_URL)
        await r.ping()
        services["redis"] = "ok"
        await r.aclose()
    except Exception as e:
        services["redis"] = f"error: {str(e)}"

    # Models Summary
    registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
    models_summary = []
    for m in registry.list_all():
        models_summary.append({
            "id": m.id,
            "name": m.name,
            "capabilities": m.capabilities
        })

    status_str = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    
    gpu_status = detect_gpus()
    gpu_info = gpu_status.model_dump() if gpu_status else None
    
    return HealthResponse(
        status=status_str,
        services=services,
        models=models_summary,
        gpu=gpu_info
    )
