"""
SAGE System Operations — execute_command tool routed through SandboxManager.
"""

from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.sandbox import SandboxManager

# Shared sandbox manager instance will be loaded lazily
_sandbox = None

def get_sandbox():
    global _sandbox
    if _sandbox is None:
        _sandbox = SandboxManager()
    return _sandbox


class ExecuteCommandTool(BaseTool):
    """Execute a terminal shell command (HIGH RISK operation)."""

    name = "execute_command"
    description = (
        "Execute a terminal shell command inside the workspace directory. "
        "This is a HIGH RISK operation that requires user approval. "
        "Use this for running system commands, installing packages, "
        "managing files via shell, or performing system operations."
    )
    permission = ToolPermission.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run",
            },
        },
        "required": ["command"],
    }

    async def execute(self, command: str) -> ToolResult:
        """Executes a command through the SandboxManager for audit and isolation."""
        result = await get_sandbox().execute_command(command=command)

        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr and not result.success:
            output_parts.append(f"STDERR:\n{result.stderr}")

        output = "\n".join(output_parts) if output_parts else "Command executed successfully (no output)"

        return ToolResult(
            success=result.success,
            output=output,
            error=f"Command failed (exit code {result.exit_code}): {result.stderr}" if not result.success else None,
            data={
                "sandbox_id": result.sandbox_id,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            },
        )
