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
from sage.tools.rag_ops import RagSearchTool, RagIngestTool

def create_default_tool_registry() -> ToolRegistry:
    """Creates a ToolRegistry with core tools and sovereign RAG tools registered."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(SearchFilesTool())
    registry.register(GetFileInfoTool())
    registry.register(ApplyPatchTool())
    registry.register(ExecuteCommandTool())
    registry.register(RagSearchTool())
    registry.register(RagIngestTool())
    return registry

