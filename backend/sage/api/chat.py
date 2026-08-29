from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from typing import Optional, List
from sage.config import settings
from sage.models.registry import ModelRegistry
from sage.agent.router import ModelRouter
from sage.tools import create_default_tool_registry
from sage.agent.profiles import ProfileManager
from sage.agent.executor import ReActExecutor
from sage.api.tasks import store_task_result
from sage.agent.state import TraceEvent

router = APIRouter()

# Shared dependencies (stateless, safe to create once)
tool_registry = create_default_tool_registry()
profile_manager = ProfileManager()

# Lazily-built executor cache — needs app.state.lifecycle_manager at runtime
_executor: Optional[ReActExecutor] = None

def _get_executor(request: Request) -> ReActExecutor:
    """
    Returns the global ReActExecutor, wiring in the lifecycle_manager 
    from app.state on first call so VRAM swaps work through the API.
    """
    global _executor
    if _executor is None:
        model_registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
        model_router = ModelRouter(model_registry)
        lifecycle_mgr = getattr(request.app.state, "lifecycle_manager", None)
        _executor = ReActExecutor(
            router=model_router,
            tool_registry=tool_registry,
            profile_manager=profile_manager,
            lifecycle_manager=lifecycle_mgr
        )
    return _executor

class CompletionRequest(BaseModel):
    prompt: str
    profile: str = "general"
    task_id: Optional[str] = None
    file_attachments: Optional[List[str]] = None

@router.post("/completions")
async def create_chat_completion(req: CompletionRequest, request: Request):
    """Executes an agent task and returns completion response with trace."""
    executor = _get_executor(request)
    response = await executor.run(
        prompt=req.prompt,
        profile_name=req.profile,
        task_id=req.task_id,
        file_attachments=req.file_attachments
    )
    store_task_result(response)
    return {
        "task_id": response.task_id,
        "status": response.status,
        "output": response.output,
        "trace": response.trace.model_dump()
    }

@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """WebSocket streaming endpoint for real-time trace events and tokens."""
    await websocket.accept()
    try:
        # Build executor with lifecycle manager from app state
        model_registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
        model_router = ModelRouter(model_registry)
        lifecycle_mgr = getattr(websocket.app.state, "lifecycle_manager", None)
        executor = ReActExecutor(
            router=model_router,
            tool_registry=tool_registry,
            profile_manager=profile_manager,
            lifecycle_manager=lifecycle_mgr
        )

        while True:
            data = await websocket.receive_text()

            async def ws_stream_callback(event: TraceEvent):
                await websocket.send_json(event.model_dump(mode="json"))

            response = await executor.run(
                prompt=data,
                task_id=session_id,
                stream_callback=ws_stream_callback
            )
            store_task_result(response)
    except WebSocketDisconnect:
        pass

