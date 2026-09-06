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
from sage.tools.code_executor import ExecuteCodeTool, RunScriptTool
from sage.tools.document_readers import (
    ReadPDFTool,
    ReadDocxTool,
    ReadXlsxTool,
    ReadImageTool,
    OCRExtractTool,
)
from sage.tools.document_generators import (
    GenerateDocxTool,
    GenerateXlsxTool,
    GeneratePptxTool,
)
from sage.tools.calculator import CalculatorTool

def create_default_tool_registry() -> ToolRegistry:
    """Creates a ToolRegistry with all 18 core tools registered."""
    registry = ToolRegistry()

    # File Operations (6 tools)
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirTool())
    registry.register(SearchFilesTool())
    registry.register(GetFileInfoTool())
    registry.register(ApplyPatchTool())

    # System & Code Execution (3 tools)
    registry.register(ExecuteCommandTool())
    registry.register(ExecuteCodeTool())
    registry.register(RunScriptTool())

    # Document Readers (5 tools)
    registry.register(ReadPDFTool())
    registry.register(ReadDocxTool())
    registry.register(ReadXlsxTool())
    registry.register(ReadImageTool())
    registry.register(OCRExtractTool())

    # Document Generators (3 tools)
    registry.register(GenerateDocxTool())
    registry.register(GenerateXlsxTool())
    registry.register(GeneratePptxTool())

    # Utilities (1 tool)
    registry.register(CalculatorTool())

    return registry
