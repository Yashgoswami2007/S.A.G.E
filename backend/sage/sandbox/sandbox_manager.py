"""
SAGE Sandbox Manager — Subprocess-based code execution engine.

Provides isolated execution of code (Python, Node.js, shell scripts, etc.)
in subprocess environments with workspace path containment and audit logging.
No timeout or memory limits — execution runs until completion or user cancellation.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

from sage.config import settings
from sage.core.utils import generate_id
from sage.sandbox.schemas import SandboxResult

logger = logging.getLogger("sage.sandbox")

# Map language identifiers to their interpreters
LANGUAGE_RUNTIMES = {
    "python": ["python", "-u"],
    "python3": ["python3", "-u"],
    "node": ["node"],
    "javascript": ["node"],
    "js": ["node"],
    "bash": ["bash"],
    "sh": ["sh"],
    "powershell": ["powershell", "-ExecutionPolicy", "Bypass", "-File"],
    "ps1": ["powershell", "-ExecutionPolicy", "Bypass", "-File"],
    "cmd": ["cmd", "/c"],
    "bat": ["cmd", "/c"],
}

# Map language to file extension
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "python3": ".py",
    "node": ".js",
    "javascript": ".js",
    "js": ".js",
    "bash": ".sh",
    "sh": ".sh",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "cmd": ".bat",
    "bat": ".bat",
    "typescript": ".ts",
    "ruby": ".rb",
    "go": ".go",
    "rust": ".rs",
    "c": ".c",
    "cpp": ".cpp",
    "java": ".java",
}


class SandboxManager:
    """
    Manages isolated code execution environments using subprocess.
    
    Each execution runs in an isolated temporary directory under
    WORKSPACE_DIR/sandbox_runs/. No timeout or memory limits are enforced —
    the user can cancel via the cancel() method.
    """

    def __init__(self):
        self._sandbox_dir = Path(settings.SANDBOX_RUNS_DIR).resolve()
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        # Track running processes for user-initiated cancellation
        self._running: Dict[str, asyncio.subprocess.Process] = {}

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        working_dir: Optional[str] = None,
    ) -> SandboxResult:
        """
        Execute a code string in an isolated subprocess.
        
        Args:
            code: The source code to execute.
            language: Programming language (python, node, bash, etc.).
            working_dir: Optional working directory within workspace.
            
        Returns:
            SandboxResult with stdout, stderr, exit code, etc.
        """
        sandbox_id = generate_id()
        lang_lower = language.lower().strip()
        ext = LANGUAGE_EXTENSIONS.get(lang_lower, ".txt")
        
        # Create isolated execution directory
        exec_dir = self._sandbox_dir / sandbox_id
        exec_dir.mkdir(parents=True, exist_ok=True)

        # Write code to a temp file
        script_file = exec_dir / f"script{ext}"
        script_file.write_text(code, encoding="utf-8")

        # Get the runtime command
        runtime = LANGUAGE_RUNTIMES.get(lang_lower)
        if not runtime:
            # For unsupported languages, try to find the interpreter in PATH
            # or just write the file and return it
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Unsupported language runtime: '{language}'. "
                       f"Supported: {', '.join(sorted(LANGUAGE_RUNTIMES.keys()))}. "
                       f"Code has been saved to: {script_file}",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
                files_created=[str(script_file.relative_to(self._sandbox_dir))],
            )

        cmd = runtime + [str(script_file)]
        cwd_path = Path(working_dir).resolve() if working_dir else exec_dir

        if not cwd_path.exists():
            cwd_path.mkdir(parents=True, exist_ok=True)
        if not cwd_path.is_dir():
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution directory is not a directory: {cwd_path}",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
                files_created=[str(script_file.relative_to(self._sandbox_dir))],
            )

        cwd = str(cwd_path)

        logger.info(
            "Sandbox %s: executing %s code (%d bytes)",
            sandbox_id, language, len(code),
        )

        return await self._run_process(
            cmd=cmd,
            cwd=cwd,
            sandbox_id=sandbox_id,
            exec_dir=exec_dir,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
        )

    async def execute_command(
        self,
        command: str,
        cwd: Optional[str] = None,
    ) -> SandboxResult:
        """
        Execute a shell command in the sandbox workspace.
        
        Args:
            command: Shell command string to execute.
            cwd: Working directory (defaults to WORKSPACE_DIR).
            
        Returns:
            SandboxResult with command output.
        """
        sandbox_id = generate_id()
        workspace = Path(settings.WORKSPACE_DIR).resolve()

        if not workspace.exists():
            workspace.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Workspace path is not a directory: {workspace}",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        # Resolve and validate cwd
        if cwd:
            resolved_cwd = Path(cwd).resolve()
            # Ensure cwd is within workspace
            try:
                resolved_cwd.relative_to(workspace)
            except ValueError:
                resolved_cwd = workspace
        else:
            resolved_cwd = workspace

        if not resolved_cwd.exists():
            resolved_cwd.mkdir(parents=True, exist_ok=True)
        if not resolved_cwd.is_dir():
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Invalid working directory: {resolved_cwd}",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        logger.info(
            "Sandbox %s: executing command: %s",
            sandbox_id, command[:200],
        )

        # Use shell execution for commands
        start_time = time.time()
        try:
            
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                
            )
            self._running[sandbox_id] = process

            stdout_bytes, stderr_bytes = await process.communicate()
            duration_ms = (time.time() - start_time) * 1000.0

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            logger.info(
                "Sandbox %s: command finished (exit=%d, %.1fms)",
                sandbox_id, exit_code, duration_ms,
            )

            return SandboxResult(
                success=exit_code == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
            )

        except FileNotFoundError as fnf:
            duration_ms = (time.time() - start_time) * 1000.0
            err_msg = f"Command shell executable not found: {str(fnf)}"
            logger.error("Sandbox %s: %s", sandbox_id, err_msg)
            return SandboxResult(
                success=False,
                stdout="",
                stderr=err_msg,
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000.0
            logger.error("Sandbox %s: command exception: %s", sandbox_id, e)
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution exception: {str(e)}",
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
            )

        finally:
            self._running.pop(sandbox_id, None)

    async def run_script(
        self,
        script_path: str,
        language: Optional[str] = None,
    ) -> SandboxResult:
        """
        Execute an existing script file from the workspace.
        
        Args:
            script_path: Workspace-relative path to the script file.
            language: Programming language (auto-detected from extension if not provided).
            
        Returns:
            SandboxResult with execution output.
        """
        sandbox_id = generate_id()
        workspace = Path(settings.WORKSPACE_DIR).resolve()
        full_path = (workspace / script_path).resolve()

        # Path containment check
        try:
            full_path.relative_to(workspace)
        except ValueError:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Path traversal blocked: '{script_path}' is outside the workspace.",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        if not full_path.exists():
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Script not found: '{script_path}'",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        if not full_path.is_file():
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Script path is not a file: '{script_path}'",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        # Auto-detect language from extension if not provided
        if not language:
            ext = full_path.suffix.lower()
            ext_to_lang = {v: k for k, v in LANGUAGE_EXTENSIONS.items()}
            language = ext_to_lang.get(ext, "python")

        lang_lower = language.lower().strip()
        runtime = LANGUAGE_RUNTIMES.get(lang_lower)

        if not runtime:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"No runtime found for language: '{language}'",
                exit_code=-1,
                duration_ms=0.0,
                sandbox_id=sandbox_id,
            )

        cmd = runtime + [str(full_path)]

        logger.info(
            "Sandbox %s: running script %s (%s)",
            sandbox_id, script_path, language,
        )

        return await self._run_process(
            cmd=cmd,
            cwd=str(full_path.parent),
            sandbox_id=sandbox_id,
            exec_dir=full_path.parent,
        )

    async def cancel(self, sandbox_id: str) -> bool:
        """
        Kill a running sandbox process.
        
        Returns True if the process was found and killed, False otherwise.
        """
        process = self._running.get(sandbox_id)
        if process and process.returncode is None:
            logger.warning("Sandbox %s: user-initiated cancellation", sandbox_id)
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            self._running.pop(sandbox_id, None)
            return True
        return False

    async def _run_process(
        self,
        cmd: list,
        cwd: str,
        sandbox_id: str,
        exec_dir: Path,
        code_hash: Optional[str] = None,
    ) -> SandboxResult:
        """Internal: run a subprocess and capture results."""
        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            self._running[sandbox_id] = process

            stdout_bytes, stderr_bytes = await process.communicate()
            duration_ms = (time.time() - start_time) * 1000.0

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            # Detect files created in the execution directory
            files_created = []
            if exec_dir.exists():
                for item in exec_dir.rglob("*"):
                    if item.is_file() and item.name != f"script{item.suffix}":
                        try:
                            files_created.append(
                                str(item.relative_to(Path(settings.WORKSPACE_DIR).resolve()))
                            )
                        except ValueError:
                            files_created.append(str(item.relative_to(exec_dir)))

            logger.info(
                "Sandbox %s: finished (exit=%d, %.1fms, %d files created)",
                sandbox_id, exit_code, duration_ms, len(files_created),
            )

            return SandboxResult(
                success=exit_code == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
                files_created=files_created,
            )

        except FileNotFoundError as fnf:
            duration_ms = (time.time() - start_time) * 1000.0
            interpreter = cmd[0] if cmd else "executable"
            err_msg = f"Runtime interpreter not found: '{interpreter}'. Ensure it is installed and available on system PATH."
            logger.error("Sandbox %s: %s", sandbox_id, err_msg)
            return SandboxResult(
                success=False,
                stdout="",
                stderr=err_msg,
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000.0
            logger.error("Sandbox %s: execution exception: %s", sandbox_id, e)
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution exception: {str(e)}",
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
            )

        finally:
            self._running.pop(sandbox_id, None)

    def cleanup(self, sandbox_id: str):
        """Remove the sandbox execution directory for a completed run."""
        exec_dir = self._sandbox_dir / sandbox_id
        if exec_dir.exists():
            shutil.rmtree(exec_dir, ignore_errors=True)
            logger.debug("Sandbox %s: cleaned up execution directory", sandbox_id)
