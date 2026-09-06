"""
SAGE Code Execution Tools — execute_code & run_script.

These tools use the SandboxManager to run code in isolated subprocess environments.
Both are HIGH_RISK and require user approval before execution.
"""

from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.sandbox import SandboxManager

# Shared sandbox manager instance
_sandbox = SandboxManager()


class ExecuteCodeTool(BaseTool):
    """Execute code (Python/JS/shell/etc.) inside a secure sandbox and return output."""

    name = "execute_code"
    description = (
        "Execute code inside a secure sandbox and return the output. "
        "Supports Python, JavaScript (Node.js), Bash, PowerShell, and more. "
        "The code runs in an isolated directory. Use this when you need to "
        "run generated code to verify it works, perform calculations, "
        "process data, or test scripts."
    )
    permission = ToolPermission.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The source code to execute",
            },
            "language": {
                "type": "string",
                "description": "Programming language (python, node, bash, powershell, etc.). Default: python",
                "default": "python",
            },
        },
        "required": ["code"],
    }

    async def execute(self, code: str, language: str = "python") -> ToolResult:
        result = await _sandbox.execute_code(code=code, language=language)

        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        if result.files_created:
            output_parts.append(f"Files created: {', '.join(result.files_created)}")
        output_parts.append(f"Exit code: {result.exit_code}")
        output_parts.append(f"Duration: {result.duration_ms:.1f}ms")

        output = "\n\n".join(output_parts)

        return ToolResult(
            success=result.success,
            output=output,
            error=result.stderr if not result.success else None,
            data={
                "sandbox_id": result.sandbox_id,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "files_created": result.files_created,
            },
        )


class RunScriptTool(BaseTool):
    """Execute an existing script file from the workspace in the sandbox."""

    name = "run_script"
    description = (
        "Execute an existing script file from the workspace in the sandbox. "
        "The language is auto-detected from the file extension if not specified. "
        "Use this to run scripts that have already been written to the workspace."
    )
    permission = ToolPermission.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the script file in the workspace",
            },
            "language": {
                "type": "string",
                "description": "Programming language (auto-detected from extension if not provided)",
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str, language: str = None) -> ToolResult:
        result = await _sandbox.run_script(script_path=path, language=language)

        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        if result.files_created:
            output_parts.append(f"Files created: {', '.join(result.files_created)}")
        output_parts.append(f"Exit code: {result.exit_code}")
        output_parts.append(f"Duration: {result.duration_ms:.1f}ms")

        output = "\n\n".join(output_parts)

        return ToolResult(
            success=result.success,
            output=output,
            error=result.stderr if not result.success else None,
            data={
                "sandbox_id": result.sandbox_id,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "files_created": result.files_created,
            },
        )
