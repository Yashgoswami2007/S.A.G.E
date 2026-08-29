from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sage.models.registry import ModelRegistry
from sage.config import settings
from sage.models.client import global_circuit_breaker

router = APIRouter()

class SwapRequest(BaseModel):
    load_id: str
    unload_id: str

@router.get("/models")
async def list_models(request: Request):
    """List all registered models (Admin only)."""
    registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
    return {"models": [m.model_dump() for m in registry.list_all()]}

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
    success = await request.app.state.lifecycle_manager.start_model(model_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start model or model not found.")
    return {"status": "success", "message": f"Model {model_id} started."}

@router.post("/models/{model_id}/stop")
async def stop_model(model_id: str, request: Request):
    """Stops a running model."""
    success = await request.app.state.lifecycle_manager.stop_model(model_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop model or model not found.")
    return {"status": "success", "message": f"Model {model_id} stopped."}

@router.post("/models/swap")
async def swap_models(swap_req: SwapRequest, request: Request):
    """Swaps two models to manage VRAM."""
    success = await request.app.state.lifecycle_manager.swap_model(swap_req.load_id, swap_req.unload_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to swap models.")
    return {"status": "success", "message": f"Swapped {swap_req.unload_id} for {swap_req.load_id}."}
