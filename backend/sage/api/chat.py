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
from sage.agent.executor import ReActExecutor, ApprovalRejectedError
from sage.api.tasks import store_task_result
from sage.agent.state import TraceEvent, AgentState
from sage.api.events import trace_to_event, sse_encode, FinalEvent, ErrorEvent

import logging

chat_logger = logging.getLogger("sage.chat")

router = APIRouter()

# Shared dependencies (stateless, safe to create once)
tool_registry = create_default_tool_registry()
profile_manager = ProfileManager()

# Lazily-built executor cache — needs app.state.lifecycle_manager at runtime
_executor: Optional[ReActExecutor] = None

# Global dictionary for pending confirmations (in-memory, single-server).
# Each entry stores: {"event": asyncio.Event, "approved": bool | None}
_pending_confirmations: Dict[str, dict] = {}

def _get_executor(request: Request) -> ReActExecutor:
    """
    Returns the global ReActExecutor, wiring in the lifecycle_manager 
    from app.state on first call so VRAM swaps work through the API.
    """
    global _executor
    if _executor is None:
        try:
            model_registry = ModelRegistry(settings.MODEL_REGISTRY_PATH)
        except Exception as exc:
            chat_logger.warning(
                "Failed to load model registry: %s. "
                "Using empty registry — the router will use its hardcoded fallback.",
                exc,
            )
            model_registry = ModelRegistry.__new__(ModelRegistry)
            model_registry.models = {}
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
    model_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None

@router.post("/completions")
async def create_chat_completion(req: CompletionRequest, request: Request):
    """Executes an agent task and returns completion response with trace."""
    try:
        executor = _get_executor(request)
        response = await executor.run(
            prompt=req.prompt,
            profile_name=req.profile,
            task_id=req.task_id,
            file_attachments=req.file_attachments,
            model_id=req.model_id,
            history=req.history
        )
        store_task_result(response)
        return {
            "task_id": response.task_id,
            "status": response.status,
            "output": response.output,
            "trace": response.trace.model_dump()
        }
    except Exception as exc:
        chat_logger.exception("Error in create_chat_completion: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Chat completion failed: {str(exc)}"
        )

class StreamRequest(BaseModel):
    prompt: str
    profile: str = "general"
    style: str = "normal"
    model_id: Optional[str] = None
    granted_paths: Optional[List[dict]] = None
    file_attachments: Optional[List[str]] = None
    history: Optional[List[Dict[str, str]]] = None

@router.post("/stream")
async def chat_stream(req: StreamRequest, request: Request):
    """Executes agent task and streams structured SSE events to the frontend."""
    executor = _get_executor(request)
    
    async def event_generator():
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def stream_callback(trace_event: TraceEvent):
            try:
                agent_event = trace_to_event(trace_event)
                if agent_event:
                    await queue.put(sse_encode(agent_event))
                
                # Handle approval wait — blocks until user approves or rejects
                if trace_event.agent_state == AgentState.WAITING_FOR_APPROVAL:
                    req_id = trace_event.id
                    confirmation_record = {
                        "event": asyncio.Event(),
                        "approved": None,  # Will be set by confirm_action
                    }
                    _pending_confirmations[req_id] = confirmation_record
                    try:
                        await confirmation_record["event"].wait()
                    finally:
                        _pending_confirmations.pop(req_id, None)

                    # After unblocking, check whether the user approved or rejected
                    if not confirmation_record["approved"]:
                        raise ApprovalRejectedError(
                            f"User rejected high-risk operation '{trace_event.tool_name}'"
                        )
            except ApprovalRejectedError:
                # Re-raise so it propagates through emit() to the executor
                raise
            except Exception as cb_err:
                chat_logger.error("Error in stream_callback: %s", cb_err, exc_info=True)

        async def run_executor():
            try:
                response = await executor.run(
                    prompt=req.prompt,
                    profile_name=req.profile,
                    file_attachments=req.file_attachments,
                    model_id=req.model_id,
                    history=req.history,
                    stream_callback=stream_callback,
                    require_approval_for_high_risk=True
                )
                store_task_result(response)
                
                # Emit FINAL event
                if response.status == AgentState.COMPLETED:
                    await queue.put(sse_encode(FinalEvent(content=response.output)))
                elif response.status == AgentState.FAILED:
                    await queue.put(sse_encode(ErrorEvent(message=f"Agent failed: {response.output}", recoverable=True)))
                    # Still send a fallback final event so frontend always receives a readable answer
                    await queue.put(sse_encode(FinalEvent(content=f"Sorry, I encountered an issue while processing your request:\n\n{response.output}")))
            except Exception as e:
                chat_logger.exception("Exception in chat_stream executor: %s", e)
                await queue.put(sse_encode(ErrorEvent(message=f"Agent execution error: {str(e)}", recoverable=True)))
                await queue.put(sse_encode(FinalEvent(content=f"Sorry, an unexpected error occurred while executing the agent:\n\n{str(e)}")))
            finally:
                await queue.put(None)

        runner_task = asyncio.create_task(run_executor())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        except asyncio.CancelledError:
            chat_logger.info("Client disconnected from chat SSE stream.")
            raise
        except Exception as gen_err:
            chat_logger.error(f"SSE event generator error: {gen_err}")
        finally:
            if not runner_task.done():
                runner_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class ConfirmRequest(BaseModel):
    request_id: str
    approved: bool

@router.post("/confirm")
async def confirm_action(req: ConfirmRequest):
    """Unblocks a pending high-risk tool operation after user approval or rejection."""
    record = _pending_confirmations.get(req.request_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Confirmation request '{req.request_id}' not found or already processed")
    
    # Store the approval decision BEFORE unblocking so the stream_callback can read it
    record["approved"] = req.approved
    record["event"].set()
    return {"status": "ok", "request_id": req.request_id, "approved": req.approved}

class ResponseConfirmationRequest(BaseModel):
    task_id: str
    prompt: str
    profile: str = "general"
    model_id: Optional[str] = None
    response_content: str
    file_attachments: Optional[List[str]] = None

@router.post("/confirm-response")
async def confirm_response(req: ResponseConfirmationRequest):
    """
    Validates a response. If empty/invalid, frontend re-triggers the executor.
    Returns: {confirmed: bool, needs_retry: bool}
    """
    content = (req.response_content or "").strip()
    is_valid = (
        len(content) >= 10
        and content != "No output generated."
        and not content.startswith("Error:")
    )
    
    if is_valid:
        return {"confirmed": True, "needs_retry": False}
    
    # Invalid — tell frontend to trigger retry
    return {"confirmed": False, "needs_retry": True}

@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """WebSocket streaming endpoint for real-time trace events and tokens."""
    await websocket.accept()
    try:
        executor = _get_executor(websocket)
        while True:
            data = await websocket.receive_text()

            async def ws_stream_callback(event: TraceEvent):
                try:
                    await websocket.send_json(event.model_dump(mode="json"))
                except Exception as ws_err:
                    chat_logger.error(f"WebSocket send error: {ws_err}")

            response = await executor.run(
                prompt=data,
                task_id=session_id,
                stream_callback=ws_stream_callback
            )
            store_task_result(response)
    except WebSocketDisconnect:
        chat_logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as e:
        chat_logger.exception("WebSocket error for session %s: %s", session_id, e)
        try:
            await websocket.send_json({"error": str(e), "type": "ERROR"})
            await websocket.close(code=1011, reason="Server error")
        except Exception:
            pass


