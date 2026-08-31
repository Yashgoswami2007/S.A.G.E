from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sage.db.session import get_db
from sage.core.schemas import HealthResponse
from sage.config import settings
from sage.models.registry import ModelRegistry
from sage.models.health import check_model_health
import httpx

router = APIRouter()

@router.get("", response_model=HealthResponse)
async def health_check(request: Request, db: AsyncSession = Depends(get_db)):
    """Returns system health status including GPU information."""
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

    # GPU Info
    gpu_info = None
    lm = getattr(request.app.state, "lifecycle_manager", None)
    hw = getattr(lm, "_hardware", None) if lm else None
    if hw and hw.selected_gpu:
        gpu_info = {
            "backend": hw.selected_backend,
            "device": hw.selected_gpu.device_name,
            "vram_total_mb": hw.selected_gpu.vram_total_mb,
            "vram_free_mb": hw.selected_gpu.vram_free_mb,
            "driver_version": hw.selected_gpu.driver_version,
        }
    elif hw:
        gpu_info = {
            "backend": hw.selected_backend,
            "device": None,
            "vram_total_mb": 0,
            "vram_free_mb": 0,
            "driver_version": None,
        }

    status_str = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    
    return HealthResponse(
        status=status_str,
        services=services,
        models=models_summary,
        gpu=gpu_info,
    )
