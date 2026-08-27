from typing import Dict, List, Optional, Set
from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.core.exceptions import ToolError

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Registers a tool instance in the registry."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Retrieves a registered tool by name."""
        return self._tools.get(name)

    def list_tools(
        self,
        allowed_tools: Optional[Set[str]] = None,
        max_permission: Optional[ToolPermission] = None
    ) -> List[BaseTool]:
        """Returns tools filtered by allowed tool names or maximum permission level."""
        permission_hierarchy = {
            ToolPermission.SAFE: 1,
            ToolPermission.MODIFY: 2,
            ToolPermission.HIGH_RISK: 3
        }
        
        result = []
        for tool in self._tools.values():
            if allowed_tools is not None and tool.name not in allowed_tools:
                continue
            if max_permission is not None:
                if permission_hierarchy[tool.permission] > permission_hierarchy[max_permission]:
                    continue
            result.append(tool)
        return result

    def get_openai_schemas(
        self,
        allowed_tools: Optional[Set[str]] = None,
        max_permission: Optional[ToolPermission] = None
    ) -> List[Dict]:
        """Generates OpenAI function calling schemas for allowed tools."""
        tools = self.list_tools(allowed_tools=allowed_tools, max_permission=max_permission)
        return [tool.to_openai_schema() for tool in tools]

    async def execute_tool(
        self,
        name: str,
        kwargs: Dict,
        allowed_tools: Optional[Set[str]] = None
    ) -> ToolResult:
        """Executes a tool after validating permissions."""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Tool '{name}' not found.")
        
        if allowed_tools is not None and name not in allowed_tools:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission Denied: Agent profile is not authorized to use tool '{name}'."
            )
            
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Tool execution exception: {str(e)}")
