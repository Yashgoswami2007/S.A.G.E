import asyncio
from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.config import settings

class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute a terminal shell command (HIGH RISK operation)."
    permission = ToolPermission.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"}
        },
        "required": ["command"]
    }

    async def execute(self, command: str) -> ToolResult:
        """Executes a command safely inside the workspace directory."""
        cwd = settings.WORKSPACE_DIR
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            
            if process.returncode == 0:
                return ToolResult(success=True, output=out_str if out_str else "Command executed successfully (no output)")
            else:
                return ToolResult(
                    success=False,
                    output=out_str,
                    error=f"Command failed (exit code {process.returncode}): {err_str}"
                )
        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error="Command execution timed out after 30 seconds")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Execution exception: {str(e)}")
