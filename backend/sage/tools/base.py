from enum import Enum
from pydantic import BaseModel
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod

class ToolPermission(str, Enum):
    SAFE = "SAFE"
    MODIFY = "MODIFY"
    HIGH_RISK = "HIGH_RISK"

class ToolResult(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class BaseTool(ABC):
    name: str
    description: str
    permission: ToolPermission = ToolPermission.SAFE
    parameters: Dict[str, Any]  # JSON Schema definition of parameters

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Executes the tool with given arguments and returns a ToolResult."""
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """Converts the tool definition into OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
