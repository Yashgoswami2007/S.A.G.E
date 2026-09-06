import logging
from typing import Dict, List, Optional, Set
from sage.tools.base import BaseTool, ToolPermission, ToolResult

logger = logging.getLogger("sage.tools.registry")

# Basic JSON-schema type → Python type mapping for validation
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}

# Common LLM argument aliases → canonical schema parameter names
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "path": ("file_path", "filepath", "filename", "file", "file_name"),
    "pattern": ("glob", "glob_pattern"),
    "query": ("search", "search_query", "text", "keyword"),
    "content": ("text", "body", "data"),
    "code": ("source", "source_code", "script"),
}


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

    @staticmethod
    def _normalize_tool_args(tool: BaseTool, kwargs: Dict) -> Dict:
        """Map common LLM argument aliases to the tool schema's canonical names."""
        properties = tool.parameters.get("properties", {})
        normalized = dict(kwargs)

        for canonical, aliases in _ARG_ALIASES.items():
            if canonical not in properties or canonical in normalized:
                continue
            for alias in aliases:
                if alias in normalized:
                    normalized[canonical] = normalized.pop(alias)
                    break

        return normalized

    # ── Argument Validation ──────────────────────────────────────────────

    @staticmethod
    def _validate_tool_args(tool: BaseTool, kwargs: Dict) -> Optional[ToolResult]:
        """Validate *kwargs* against the tool's own ``parameters`` JSON schema.

        Returns ``None`` when validation passes, or a failed ``ToolResult``
        with a descriptive error message when it does not.

        Checks performed (in order):
        1. No unexpected arguments (keys not in schema ``properties``).
        2. All ``required`` arguments are present.
        3. Basic type checking for each provided argument.
        """
        schema = tool.parameters
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        provided = set(kwargs.keys())
        valid_names = sorted(properties.keys())

        # 1. Unexpected arguments
        unexpected = provided - set(properties.keys())
        if unexpected:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Tool '{tool.name}' received unexpected arguments: {sorted(unexpected)}. "
                    f"Valid arguments: {valid_names}"
                ),
            )

        # 2. Missing required arguments
        missing = required - provided
        if missing:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Tool '{tool.name}' missing required arguments: {sorted(missing)}. "
                    f"Required: {sorted(required)}"
                ),
            )

        # 3. Basic type validation
        for key, value in kwargs.items():
            expected_type_str = properties.get(key, {}).get("type")
            if not expected_type_str:
                continue

            valid = True
            if expected_type_str == "integer":
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif expected_type_str == "number":
                valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            elif expected_type_str in _JSON_TYPE_MAP:
                py_type = _JSON_TYPE_MAP[expected_type_str]
                valid = isinstance(value, py_type)

            if not valid:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Tool '{tool.name}' argument '{key}' expected type "
                        f"'{expected_type_str}', got {type(value).__name__}"
                    ),
                )

        return None  # Validation passed

    def validate_tool_call(self, name: str, kwargs: Optional[Dict] = None) -> None:
        """Validate a tool call against the registry schema without executing it.

        Raises:
            ValueError: If the tool does not exist, has unexpected arguments,
                        is missing required arguments, or arguments have invalid types.
        """
        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Unknown tool: '{name}'")

        normalized = self._normalize_tool_args(tool, kwargs or {})
        err = self._validate_tool_args(tool, normalized)
        if err is not None:
            raise ValueError(err.error)

    # ── Execution ────────────────────────────────────────────────────────

    async def execute_tool(
        self,
        name: str,
        kwargs: Dict,
        allowed_tools: Optional[Set[str]] = None
    ) -> ToolResult:
        """Executes a tool after validating permissions and arguments."""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Tool '{name}' not found.")
        
        if allowed_tools is not None and name not in allowed_tools:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission Denied: Agent profile is not authorized to use tool '{name}'."
            )

        kwargs = self._normalize_tool_args(tool, kwargs or {})

        # Validate arguments against the tool's JSON schema
        validation_error = self._validate_tool_args(tool, kwargs)
        if validation_error is not None:
            logger.warning(
                "Tool '%s' argument validation failed: %s", name, validation_error.error
            )
            return validation_error

        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Tool execution exception: {str(e)}")
