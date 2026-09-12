from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel
from sage.agent.state import TraceEvent, AgentState

# Event Models

class PlanStep(BaseModel):
    id: int
    description: str
    tool: Optional[str] = None

class PlanCreatedEvent(BaseModel):
    type: Literal["PLAN_CREATED"] = "PLAN_CREATED"
    plan: Dict[str, Any]  # { summary: str, steps: List[PlanStep] }

class ToolCallEvent(BaseModel):
    type: Literal["TOOL_CALL"] = "TOOL_CALL"
    step_id: int
    tool_name: str
    tool_args: Dict[str, Any]

class ToolResultEvent(BaseModel):
    type: Literal["TOOL_RESULT"] = "TOOL_RESULT"
    step_id: int
    tool_name: str
    success: bool
    output: str
    error: Optional[str] = None

class ThinkingEvent(BaseModel):
    type: Literal["THINKING"] = "THINKING"
    content: str

class FileCreatedEvent(BaseModel):
    type: Literal["FILE_CREATED"] = "FILE_CREATED"
    path: str
    size_bytes: int

class FileModifiedEvent(BaseModel):
    type: Literal["FILE_MODIFIED"] = "FILE_MODIFIED"
    path: str
    diff_summary: str

class CommandStartedEvent(BaseModel):
    type: Literal["COMMAND_STARTED"] = "COMMAND_STARTED"
    command: str
    step_id: int

class CommandFinishedEvent(BaseModel):
    type: Literal["COMMAND_FINISHED"] = "COMMAND_FINISHED"
    exit_code: int
    stdout: str
    stderr: str

class ErrorEvent(BaseModel):
    type: Literal["ERROR"] = "ERROR"
    message: str
    recoverable: bool

class ConfirmationRequiredEvent(BaseModel):
    type: Literal["CONFIRMATION_REQUIRED"] = "CONFIRMATION_REQUIRED"
    action: str
    description: str
    request_id: str
    tool_args: Dict[str, Any] = {}

class FinalEvent(BaseModel):
    type: Literal["FINAL"] = "FINAL"
    content: str

class TokenEvent(BaseModel):
    type: Literal["TOKEN"] = "TOKEN"
    token: str

class ToolSynthesisProgressEvent(BaseModel):
    type: Literal["TOOL_SYNTHESIS_PROGRESS"] = "TOOL_SYNTHESIS_PROGRESS"
    stage: str
    message: str
    attempt: Optional[int] = None
    max_attempts: Optional[int] = None
    tool_name: Optional[str] = None
    tool_factory_id: Optional[str] = None

AgentEvent = Union[
    PlanCreatedEvent,
    ToolCallEvent,
    ToolResultEvent,
    ThinkingEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    CommandStartedEvent,
    CommandFinishedEvent,
    ErrorEvent,
    ConfirmationRequiredEvent,
    FinalEvent,
    TokenEvent,
    ToolSynthesisProgressEvent,
]

def trace_to_event(trace: TraceEvent, plan: Optional[Any] = None) -> Optional[AgentEvent]:
    """Maps internal execution trace events to frontend agent events."""
    if trace.token is not None:
        return TokenEvent(token=trace.token)

    if trace.agent_state == AgentState.PLANNING:
        if trace.tool_args and "plan" in trace.tool_args:
            return PlanCreatedEvent(plan=trace.tool_args["plan"])
        if plan:
            return PlanCreatedEvent(
                plan={
                    "summary": plan.summary,
                    "steps": [
                        {"id": step.step_id, "description": step.description, "tool": step.tool_name}
                        for step in plan.steps
                    ]
                }
            )
        return None

    if trace.agent_state == AgentState.ACTING:
        if trace.tool_name:
            return ToolCallEvent(
                step_id=trace.step_id or 0,
                tool_name=trace.tool_name,
                tool_args=trace.tool_args or {}
            )
            
    if trace.agent_state == AgentState.TOOL_SYNTHESIS:
        if trace.synthesis_info:
            return ToolSynthesisProgressEvent(
                stage=trace.synthesis_info.get("stage", "UNKNOWN"),
                message=trace.synthesis_info.get("message", ""),
                attempt=trace.synthesis_info.get("attempt"),
                max_attempts=trace.synthesis_info.get("max_attempts"),
                tool_name=trace.synthesis_info.get("tool_name"),
                tool_factory_id=trace.synthesis_info.get("tool_factory_id")
            )
    
    if trace.agent_state == AgentState.OBSERVING:
        if trace.tool_name:
            success = not trace.error
            return ToolResultEvent(
                step_id=trace.step_id or 0,
                tool_name=trace.tool_name,
                success=success,
                output=trace.tool_result or "",
                error=trace.error
            )
        elif trace.reflection:
            return ThinkingEvent(content=trace.reflection)
    
    if trace.agent_state == AgentState.REFLECTING:
        if trace.reflection:
            return ThinkingEvent(content=trace.reflection)
            
    if trace.agent_state == AgentState.WAITING_FOR_APPROVAL:
        return ConfirmationRequiredEvent(
            action=trace.tool_name or "Unknown Action",
            description=trace.reflection or "High risk operation requires approval.",
            request_id=trace.id,
            tool_args=trace.tool_args or {}
        )
        
    if trace.agent_state == AgentState.FAILED:
        return ErrorEvent(
            message=trace.error or "Unknown error occurred",
            recoverable=False
        )

    return None

def sse_encode(event: AgentEvent) -> str:
    """Encodes an event to Server-Sent Events format."""
    return f"data: {event.model_dump_json()}\n\n"
