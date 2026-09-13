import json
import logging
from typing import Any, Dict, Optional
from pathlib import Path
from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.tool_factory.models import ToolSpecification
from sage.sandbox.sandbox_manager import SandboxManager
from sage.config import settings

logger = logging.getLogger("sage.tools.dynamic_runtime")

class DynamicTool(BaseTool):
    """A tool that executes dynamically generated code inside a sandbox."""

    def __init__(self, spec: ToolSpecification, code_path: str, sandbox_manager: SandboxManager):
        self.spec = spec
        self.name = spec.name
        self.description = spec.description
        self.parameters = spec.input_schema
        # Map dynamic permissions to our basic ToolPermission enum for the executor UI
        self.permission = ToolPermission.HIGH_RISK if (spec.permissions.network or spec.permissions.subprocess) else ToolPermission.MODIFY
        
        self.code_path = Path(code_path)
        self.sandbox_manager = sandbox_manager

    async def execute(self, **kwargs) -> ToolResult:
        """Executes the dynamic tool in the sandbox."""
        logger.info(f"Executing dynamic tool '{self.name}' via sandbox.")
        
        # Read the code from the registered path
        if not self.code_path.exists():
            return ToolResult(success=False, output="", error=f"Tool code not found at {self.code_path}")
            
        tool_code = self.code_path.read_text(encoding="utf-8")
        
        # We need a wrapper script to instantiate the class and call it, then print JSON.
        wrapper_script = (
            f"{tool_code}\n\n"
            f"import asyncio\n"
            f"import json\n"
            f"import sys\n"
            f"async def __main__():\n"
            f"    try:\n"
            f"        # Assuming the LLM generated a class with the same name as the tool but PascalCased, "
            f"        # or we just find the first class that inherits from BaseTool.\n"
            f"        tool_class = next(c for n, c in globals().items() if isinstance(c, type) and c.__name__ != 'BaseTool' and issubclass(c, BaseTool))\n"
            f"        tool_instance = tool_class()\n"
            f"        kwargs = {json.dumps(kwargs)}\n"
            f"        result = await tool_instance.execute(**kwargs)\n"
            f"        print(json.dumps({{'success': result.success, 'output': result.output, 'error': result.error}}))\n"
            f"    except Exception as e:\n"
            f"        print(json.dumps({{'success': False, 'output': '', 'error': str(e)}}))\n"
            f"asyncio.run(__main__())\n"
        )
        
        # Run it in sandbox with workspace containment
        result = await self.sandbox_manager.execute_code(
            wrapper_script, 
            language="python",
            working_dir=settings.WORKSPACE_DIR
        )
        
        if not result.success:
            return ToolResult(
                success=False, 
                output="", 
                error=f"Dynamic tool execution failed (exit {result.exit_code}):\n{result.stderr}\n{result.stdout}"
            )
            
        # Parse the JSON from stdout
        # Find the last line that is valid JSON
        stdout_lines = result.stdout.strip().split("\n")
        for line in reversed(stdout_lines):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict) and "success" in parsed:
                    return ToolResult(
                        success=parsed["success"],
                        output=parsed.get("output", ""),
                        error=parsed.get("error")
                    )
            except json.JSONDecodeError:
                continue
                
        return ToolResult(
            success=False,
            output="",
            error=f"Could not parse ToolResult from dynamic tool output.\nStdout: {result.stdout}\nStderr: {result.stderr}"
        )
