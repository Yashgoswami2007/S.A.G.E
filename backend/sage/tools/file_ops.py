import json
import logging
import aiofiles
from pathlib import Path
from typing import Optional
from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.config import settings

logger = logging.getLogger("sage.tools.file_ops")

def _resolve_path(path_str: str) -> Path:
    """Resolves relative paths against workspace directory and enforces containment."""
    base_dir = Path(settings.WORKSPACE_DIR).resolve()
    target_path = (base_dir / path_str).resolve()
    # Containment check to prevent directory traversal
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise PermissionError(
            f"Path escapes workspace: {path_str}"
        )
    return target_path

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read contents of a file from the workspace."
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file in workspace"}
        },
        "required": ["path"]
    }

    async def execute(self, path: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"File not found: {path}")
            async with aiofiles.open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = await f.read()
            return ToolResult(success=True, output=content)
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read file '{path}': {str(e)}")

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file in the workspace."
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "content": {"type": "string", "description": "File content to write"}
        },
        "required": ["path", "content"]
    }

    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)
            return ToolResult(success=True, output=f"Successfully wrote {len(content)} bytes to {path}")
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to write file '{path}': {str(e)}")

class ListDirTool(BaseTool):
    name = "list_dir"
    description = (
        "List files and directories inside the SAGE workspace. "
        "Never use absolute paths."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional relative path inside the workspace. Defaults to '.'."
            }
        },
        "required": []
    }

    async def execute(self, path: str = ".") -> ToolResult:
        try:
            full_path = _resolve_path(path)
            logger.debug(
                "LIST_DIR: input=%r resolved=%s exists=%s is_dir=%s",
                path, full_path, full_path.exists(), full_path.is_dir(),
            )
            if not full_path.exists() or not full_path.is_dir():
                logger.warning("LIST_DIR: directory not found: input=%r resolved=%s", path, full_path)
                return ToolResult(success=False, output="", error=f"Directory not found: {path}")

            entries = []
            for item in full_path.iterdir():
                kind = "DIR" if item.is_dir() else "FILE"
                size = item.stat().st_size if item.is_file() else 0
                entries.append(f"[{kind}] {item.name} ({size} bytes)")
            out = "\n".join(sorted(entries)) if entries else "(Empty directory)"
            return ToolResult(success=True, output=out)
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            logger.error("LIST_DIR exception: %s", e, exc_info=True)
            return ToolResult(success=False, output="", error=f"Failed to list directory '{path}': {str(e)}")

class SearchFilesTool(BaseTool):
    name = "search_files"
    description = (
        "Search files recursively within the SAGE workspace by filename pattern, "
        "and optionally search text inside matching files. "
        "The search root is always the workspace."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Filename glob pattern, e.g. '*.pdf', '*.py', '*'"
            },
            "query": {
                "type": "string",
                "description": "Optional text to search inside matching files"
            }
        },
        "required": ["pattern"]
    }

    async def execute(self, pattern: str, query: Optional[str] = None) -> ToolResult:
        try:
            base_dir = _resolve_path(".")
            matches = []
            for p in base_dir.rglob(pattern):
                if p.is_file():
                    rel = p.relative_to(base_dir)
                    if query:
                        try:
                            async with aiofiles.open(p, "r", encoding="utf-8", errors="ignore") as f:
                                text = await f.read()
                                if query in text:
                                    matches.append(f"{rel} (matches text)")
                        except Exception:
                            pass
                    else:
                        matches.append(str(rel))
            out = "\n".join(matches) if matches else "No matching files found."
            return ToolResult(success=True, output=out)
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"File search failed: {str(e)}")

class GetFileInfoTool(BaseTool):
    name = "get_file_info"
    description = "Get file metadata (size, created time, modified time)."
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"}
        },
        "required": ["path"]
    }

    async def execute(self, path: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists():
                return ToolResult(success=False, output="", error=f"Path not found: {path}")
            stat = full_path.stat()
            info = {
                "name": full_path.name,
                "is_dir": full_path.is_dir(),
                "size_bytes": stat.st_size,
                "modified_time": stat.st_mtime,
                "created_time": stat.st_ctime
            }
            return ToolResult(success=True, output=json.dumps(info, indent=2), data=info)
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to get file info: {str(e)}")

class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = "Safely replace exact target content with new content in an existing file."
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "target": {"type": "string", "description": "Exact content string to replace"},
            "replacement": {"type": "string", "description": "New content string to insert"}
        },
        "required": ["path", "target", "replacement"]
    }

    async def execute(self, path: str, target: str, replacement: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"File not found: {path}")
            async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                content = await f.read()
            if target not in content:
                return ToolResult(success=False, output="", error=f"Target content string not found in {path}")
            new_content = content.replace(target, replacement, 1)
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(new_content)
            return ToolResult(success=True, output=f"Successfully applied patch to {path}")
        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to patch file '{path}': {str(e)}")

