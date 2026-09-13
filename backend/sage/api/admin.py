from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sage.models.registry import ModelRegistry
from sage.config import settings
from sage.models.client import global_circuit_breaker
from sage.models.gpu_detector import detect_gpus

router = APIRouter()

class SwapRequest(BaseModel):
    load_id: str
    unload_id: str

@router.get("/models")
async def list_models(request: Request):
    """List all registered models (Admin only)."""
    registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
    return {"models": [m.model_dump() for m in registry.list_all()]}

@router.get("/models/available")
async def list_available_models(request: Request):
    """
    Returns all models from the live registry with status, capabilities,
    and vision support flags. Used by the frontend model picker.
    """
    registry = request.app.state.lifecycle_manager.registry
    models_out = []
    for m in registry.list_all():
        models_out.append({
            "id": m.id,
            "name": m.name,
            "status": m.status,
            "capabilities": m.capabilities,
            "supports_vision": m.supports_vision,
            "supports_image_upload": m.supports_image_upload,
            "supports_files": m.supports_files,
            "min_vram_gb": m.min_vram_gb,
            "context_length": m.context_length,
            "is_default": m.auto_start,
        })
    return {"models": models_out}

@router.post("/models/{model_id}/activate")
async def activate_model(model_id: str, request: Request):
    """
    Activates a model for use. If another model is loaded,
    swaps it out first (VRAM constraint — only one model at a time).
    Returns status and model_id when ready.
    """
    lifecycle = request.app.state.lifecycle_manager
    registry = lifecycle.registry

    target = registry.models.get(model_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in registry.")

    if target.status == "READY":
        return {"status": "already_ready", "model_id": model_id}

    if not lifecycle._check_model_file(target):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot activate '{model_id}': Model file not found at '{target.model_path}'."
        )

    # Find currently loaded model(s) to unload (VRAM constraint: one at a time)
    currently_loaded = [m for m in registry.list_all() if m.status in ("READY", "DEGRADED")]
    
    if currently_loaded:
        # Swap: unload current, load requested
        success = await lifecycle.swap_model(
            load_id=model_id,
            unload_id=currently_loaded[0].id
        )
    else:
        success = await lifecycle.start_model(model_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to activate model '{model_id}'. Check server logs, VRAM availability, and model binary."
        )

    return {"status": "ready", "model_id": model_id}

@router.get("/gpu")
async def get_gpu_status(request: Request):
    """Get GPU status."""
    status = detect_gpus()
    return status.model_dump() if status else {}

@router.get("/models/status")
async def get_models_status(request: Request):
    """Get live status of all models including circuit breaker state."""
    registry = request.app.state.lifecycle_manager.registry
    status_list = []
    for model in registry.list_all():
        cb_state = global_circuit_breaker.get_state(model.id).value
        status_list.append({
            "id": model.id,
            "status": model.status,
            "circuit_breaker": cb_state
        })
    return {"models": status_list}

@router.post("/models/{model_id}/start")
async def start_model(model_id: str, request: Request):
    """Starts a model on-demand."""
    lifecycle = request.app.state.lifecycle_manager
    if model_id not in lifecycle.registry.models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in registry.")

    success = await lifecycle.start_model(model_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to start model '{model_id}'. Check file path and port availability.")
    return {"status": "success", "message": f"Model {model_id} started."}

@router.post("/models/{model_id}/stop")
async def stop_model(model_id: str, request: Request):
    """Stops a running model."""
    lifecycle = request.app.state.lifecycle_manager
    if model_id not in lifecycle.registry.models:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in registry.")

    success = await lifecycle.stop_model(model_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to stop model '{model_id}'.")
    return {"status": "success", "message": f"Model {model_id} stopped."}

@router.post("/models/swap")
async def swap_models(swap_req: SwapRequest, request: Request):
    """Swaps two models to manage VRAM."""
    lifecycle = request.app.state.lifecycle_manager
    if swap_req.load_id not in lifecycle.registry.models:
        raise HTTPException(status_code=404, detail=f"Model '{swap_req.load_id}' not found in registry.")
    if swap_req.unload_id not in lifecycle.registry.models:
        raise HTTPException(status_code=404, detail=f"Model '{swap_req.unload_id}' not found in registry.")

    success = await lifecycle.swap_model(swap_req.load_id, swap_req.unload_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to swap models '{swap_req.unload_id}' -> '{swap_req.load_id}'.")
    return {"status": "success", "message": f"Swapped {swap_req.unload_id} for {swap_req.load_id}."}

