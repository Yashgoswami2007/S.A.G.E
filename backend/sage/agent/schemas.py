from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from sage.agent.state import AgentState, ExecutionTrace

class Step(BaseModel):
    step_id: int
    description: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED, FAILED

class Plan(BaseModel):
    summary: str
    steps: List[Step]

class StepResult(BaseModel):
    step_id: int
    success: bool
    output: str
    error: Optional[str] = None

class AgentTask(BaseModel):
    task_id: str
    prompt: str
    profile: str
    state: AgentState = AgentState.PLANNING
    trace: ExecutionTrace

class AgentResponse(BaseModel):
    task_id: str
    status: AgentState
    output: str
    trace: ExecutionTrace
