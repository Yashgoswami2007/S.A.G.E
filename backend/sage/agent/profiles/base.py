from pydantic import BaseModel
from typing import Set, Optional
from sage.tools.base import ToolPermission

class AgentProfile(BaseModel):
    name: str
    description: str
    model_preference: str  # reasoning, coding, vision
    max_permission: ToolPermission = ToolPermission.SAFE
    allowed_tools: Set[str]  # Set of tool names allowed for this profile

    def is_tool_allowed(self, tool_name: str, tool_permission: ToolPermission) -> bool:
        """Checks if a tool is permitted under this profile."""
        if tool_name not in self.allowed_tools:
            return False
        
        hierarchy = {
            ToolPermission.SAFE: 1,
            ToolPermission.MODIFY: 2,
            ToolPermission.HIGH_RISK: 3
        }
        return hierarchy[tool_permission] <= hierarchy[self.max_permission]
