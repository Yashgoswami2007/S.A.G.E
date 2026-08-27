from sage.tools.registry import ToolRegistry
from sage.tools.file_ops import (
    ReadFileTool,
    WriteFileTool,
    ListDirTool,
    SearchFilesTool,
    GetFileInfoTool,
    ApplyPatchTool,
)
from sage.tools.system_ops import ExecuteCommandTool

def create_default_tool_registry() -> ToolRegistry:
    """Creates a ToolRegistry with all 7 core tools registered."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(SearchFilesTool())
    registry.register(GetFileInfoTool())
    registry.register(ApplyPatchTool())
    registry.register(ExecuteCommandTool())
    return registry
