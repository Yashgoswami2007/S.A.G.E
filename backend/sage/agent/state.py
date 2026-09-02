from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from sage.core.utils import generate_id, utc_now

class AgentState(str, Enum):
    PLANNING = "PLANNING"
    ACTING = "ACTING"
    OBSERVING = "OBSERVING"
    REFLECTING = "REFLECTING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class TraceEvent(BaseModel):
    id: str = Field(default_factory=generate_id)
    timestamp: datetime = Field(default_factory=utc_now)
    task_id: str
    step_id: Optional[int] = None
    agent_state: AgentState
    profile: str
    selected_model: Optional[str] = None
    routing_reason: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[str] = None
    duration_ms: float = 0.0
    retry_count: int = 0
    error: Optional[str] = None
    reflection: Optional[str] = None
    token: Optional[str] = None

class ExecutionTrace(BaseModel):
    task_id: str
    prompt: str
    profile_name: str
    selected_model: str
    routing_reason: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    events: List[TraceEvent] = Field(default_factory=list)

    def add_event(self, event: TraceEvent):
        self.events.append(event)
        self.updated_at = utc_now()
