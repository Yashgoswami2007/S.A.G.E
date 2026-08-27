from fastapi import APIRouter, HTTPException
from typing import Dict
from sage.agent.state import ExecutionTrace
from sage.agent.schemas import AgentResponse

router = APIRouter()

# Global in-memory task store for persistent traces during runtime
TASK_STORE: Dict[str, AgentResponse] = {}

def store_task_result(response: AgentResponse):
    TASK_STORE[response.task_id] = response

@router.get("/{task_id}")
async def get_task_status(task_id: str):
    """Retrieves execution status and trace history for a given task."""
    if task_id not in TASK_STORE:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    res = TASK_STORE[task_id]
    return {
        "task_id": res.task_id,
        "status": res.status,
        "output": res.output,
        "trace": res.trace.model_dump()
    }
