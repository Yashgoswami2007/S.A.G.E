from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import asyncio
import json
from sage.config import settings
from sage.models.registry import ModelRegistry
from sage.agent.router import ModelRouter
from sage.tools import create_default_tool_registry
from sage.agent.profiles import ProfileManager
from sage.agent.executor import ReActExecutor
from sage.api.tasks import store_task_result
from sage.agent.state import TraceEvent, AgentState
from sage.api.events import trace_to_event, sse_encode, FinalEvent, ErrorEvent

router = APIRouter()

# Shared dependencies (stateless, safe to create once)
tool_registry = create_default_tool_registry()
profile_manager = ProfileManager()

# Lazily-built executor cache — needs app.state.lifecycle_manager at runtime
_executor: Optional[ReActExecutor] = None

# Global dictionary for pending confirmations (in-memory, single-server)
_pending_confirmations: Dict[str, asyncio.Event] = {}

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

class StreamRequest(BaseModel):
    prompt: str
    profile: str = "general"
    style: str = "normal"
    granted_paths: Optional[List[dict]] = None
    file_attachments: Optional[List[str]] = None

@router.post("/stream")
async def chat_stream(req: StreamRequest, request: Request):
    """Executes agent task and streams structured SSE events to the frontend."""
    executor = _get_executor(request)
    
    async def event_generator():
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def stream_callback(trace_event: TraceEvent):
            agent_event = trace_to_event(trace_event)
            if agent_event:
                if getattr(agent_event, "type", "") == "TOKEN":
                    print(f"[BACKEND] token generated: {repr(getattr(agent_event, 'token', ''))}")
                print(f"[BACKEND] SSE event emitted: {getattr(agent_event, 'type', '')}")
                await queue.put(sse_encode(agent_event))
            
            # Handle approval wait
            if trace_event.agent_state == AgentState.WAITING_FOR_APPROVAL:
                req_id = trace_event.id
                approval_event = asyncio.Event()
                _pending_confirmations[req_id] = approval_event
                try:
                    await approval_event.wait()
                finally:
                    _pending_confirmations.pop(req_id, None)

        async def run_executor():
            try:
                response = await executor.run(
                    prompt=req.prompt,
                    profile_name=req.profile,
                    file_attachments=req.file_attachments,
                    stream_callback=stream_callback,
                    require_approval_for_high_risk=True
                )
                store_task_result(response)
                
                # Emit FINAL event
                if response.status == AgentState.COMPLETED:
                    await queue.put(sse_encode(FinalEvent(content=response.output)))
                elif response.status == AgentState.FAILED:
                    await queue.put(sse_encode(ErrorEvent(message=f"Agent failed: {response.output}", recoverable=False)))
            except Exception as e:
                await queue.put(sse_encode(ErrorEvent(message=str(e), recoverable=False)))
            finally:
                await queue.put(None)

        runner_task = asyncio.create_task(run_executor())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not runner_task.done():
                runner_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class ConfirmRequest(BaseModel):
    request_id: str
    approved: bool

@router.post("/confirm")
async def confirm_action(req: ConfirmRequest):
    """Unblocks a pending high-risk tool operation."""
    event = _pending_confirmations.get(req.request_id)
    if not event:
        raise HTTPException(status_code=404, detail="Confirmation request not found or already processed")
    
    # For now we just resume on any response. If approved=False, ideally we should 
    # tell the executor to cancel the tool call, but the executor currently just blocks.
    # A true deny would involve raising an exception in the callback or setting a flag.
    # Assuming approved=True for the happy path right now.
    event.set()
    return {"status": "ok"}

@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """WebSocket streaming endpoint for real-time trace events and tokens."""
    await websocket.accept()
    try:
        executor = _get_executor(websocket)
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

