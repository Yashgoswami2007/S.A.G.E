import os
import sys
import subprocess
import base64
import logging
import mimetypes
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query

import sage.workspace as _ws_module
from sage.workspace.models import (
    WorkspaceInfo, WorkspaceValidation, 
    SetWorkspaceRequest, ValidateWorkspaceRequest, RemoveRecentRequest
)
from sage.core.exceptions import WorkspaceInvalidError

logger = logging.getLogger("sage.api.workspace")

router = APIRouter()

# ── File type classification ──────────────────────────────────────────────
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml",
    ".yml", ".csv", ".html", ".css", ".scss", ".xml", ".toml", ".ini",
    ".cfg", ".conf", ".sh", ".bash", ".bat", ".ps1", ".sql", ".r", ".rs",
    ".go", ".java", ".kt", ".c", ".cpp", ".h", ".hpp", ".rb", ".lua",
    ".swift", ".dart", ".vue", ".svelte", ".graphql", ".proto", ".env",
    ".gitignore", ".dockerignore", ".editorconfig", ".log", ".makefile",
    ".cmake", ".tf", ".hcl",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
XLSX_EXTENSIONS = {".xlsx"}
MARKDOWN_EXTENSIONS = {".md"}

MAX_TEXT_BYTES = 1 * 1024 * 1024      # 1 MB
MAX_BINARY_BYTES = 10 * 1024 * 1024   # 10 MB

# Dependency to ensure workspace_manager is initialized.
# We access _ws_module.workspace_manager (an attribute lookup) each time,
# so we always see the current value even after init_workspace_manager()
# replaces the module-level None with a real WorkspaceManager instance.
def get_manager():
    if _ws_module.workspace_manager is None:
        _ws_module.init_workspace_manager()
    return _ws_module.workspace_manager

@router.get("", response_model=WorkspaceInfo)
async def get_workspace(manager = Depends(get_manager)):
    """Get the current workspace info."""
    return manager.get_workspace_info()

@router.post("/validate", response_model=WorkspaceValidation)
async def validate_workspace(req: ValidateWorkspaceRequest, manager = Depends(get_manager)):
    """Validate a candidate path without changing the active workspace."""
    return manager.validate_workspace(req.path)

@router.post("/set", response_model=WorkspaceInfo)
async def set_workspace(req: SetWorkspaceRequest, manager = Depends(get_manager)):
    """Set the active workspace, saving it to state and syncing settings."""
    try:
        return manager.set_active_workspace(req.path)
    except WorkspaceInvalidError as e:
        # Wrap it so SAGEError exception handler catches it properly
        raise e

@router.post("/reset", response_model=WorkspaceInfo)
async def reset_workspace(manager = Depends(get_manager)):
    """Reset the active workspace to the default workspace."""
    return manager.reset_to_default()

@router.get("/recent", response_model=list[str])
async def get_recent_workspaces(manager = Depends(get_manager)):
    """Get the list of recent workspaces."""
    return manager.get_recent_workspaces()

@router.delete("/recent")
async def remove_recent_workspace(req: RemoveRecentRequest, manager = Depends(get_manager)):
    """Remove a workspace from the recent list."""
    manager.remove_recent_workspace(req.path)
    return {"success": True}

@router.post("/open-folder")
async def open_workspace_folder(manager = Depends(get_manager)):
    """Open the active workspace folder in the OS file explorer."""
    path = manager.get_active_workspace()
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}")


# ── File Browsing Endpoints ───────────────────────────────────────────────

@router.get("/files")
async def list_files(
    path: str = Query("", description="Relative path within workspace (empty = root)"),
    manager = Depends(get_manager),
):
    """List files and folders in the given directory within the active workspace."""
    try:
        base = Path(manager.get_active_workspace()).resolve()
        target = (base / path).resolve() if path else base

        # Enforce containment
        try:
            target.relative_to(base)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes the workspace boundary.")

        if not target.exists():
            raise HTTPException(status_code=404, detail="Directory not found.")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory.")

        entries = []
        try:
            for entry in target.iterdir():
                # Skip hidden files/folders (starting with .)
                if entry.name.startswith("."):
                    continue
                try:
                    stat = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": stat.st_size if entry.is_file() else None,
                        "modified": stat.st_mtime,
                    })
                except (PermissionError, OSError):
                    # Skip files we can't stat
                    continue
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied reading directory.")

        # Sort: directories first, then alphabetical (case-insensitive)
        entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
        return entries

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {e}")


@router.get("/files/read")
async def read_file(
    path: str = Query(..., description="Relative path to the file within workspace"),
    manager = Depends(get_manager),
):
    """Read a file's content from the active workspace, returning type-appropriate data."""
    try:
        base = Path(manager.get_active_workspace()).resolve()
        target = (base / path).resolve()

        # Enforce containment
        try:
            target.relative_to(base)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes the workspace boundary.")

        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file.")

        ext = target.suffix.lower()
        file_size = target.stat().st_size
        file_name = target.name

        # ── Text / Code files ──
        if ext in TEXT_EXTENSIONS or file_name in {
            "Makefile", "Dockerfile", "Vagrantfile", "Rakefile",
            "Gemfile", "Procfile", "LICENSE", "README", "CHANGELOG",
        }:
            if file_size > MAX_TEXT_BYTES:
                return {
                    "type": "text",
                    "content": f"[File too large to preview: {file_size:,} bytes. Max is {MAX_TEXT_BYTES:,} bytes.]",
                    "name": file_name,
                    "size": file_size,
                    "truncated": True,
                }
            content = target.read_text(encoding="utf-8", errors="replace")

            # For Markdown files, also produce an HTML rendering
            if ext in MARKDOWN_EXTENSIONS:
                html_content = None
                try:
                    import markdown
                    html_content = markdown.markdown(
                        content,
                        extensions=["fenced_code", "tables", "toc", "nl2br"],
                    )
                except ImportError:
                    pass  # Fall back to raw text only
                return {
                    "type": "markdown",
                    "content": content,
                    "html": html_content,
                    "name": file_name,
                    "size": file_size,
                }

            return {"type": "text", "content": content, "name": file_name, "size": file_size}

        # ── Images ──
        if ext in IMAGE_EXTENSIONS:
            if file_size > MAX_BINARY_BYTES:
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "Image too large to preview."}
            data = target.read_bytes()
            mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            return {
                "type": "image",
                "content": base64.b64encode(data).decode("ascii"),
                "mime": mime,
                "name": file_name,
                "size": file_size,
            }

        # ── PDF ──
        if ext in PDF_EXTENSIONS:
            if file_size > MAX_BINARY_BYTES:
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "PDF too large to preview."}
            data = target.read_bytes()
            return {
                "type": "pdf",
                "content": base64.b64encode(data).decode("ascii"),
                "name": file_name,
                "size": file_size,
            }

        # ── DOCX ──
        if ext in DOCX_EXTENSIONS:
            if file_size > MAX_BINARY_BYTES:
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "Document too large to preview."}
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(target))
                # Build a simple HTML representation
                html_parts = []
                for para in doc.paragraphs:
                    style_name = (para.style.name or "").lower()
                    text = para.text
                    if not text.strip():
                        html_parts.append("<br/>")
                        continue
                    if "heading 1" in style_name:
                        html_parts.append(f"<h1>{text}</h1>")
                    elif "heading 2" in style_name:
                        html_parts.append(f"<h2>{text}</h2>")
                    elif "heading 3" in style_name:
                        html_parts.append(f"<h3>{text}</h3>")
                    else:
                        html_parts.append(f"<p>{text}</p>")
                return {
                    "type": "docx",
                    "content": "\n".join(html_parts),
                    "name": file_name,
                    "size": file_size,
                }
            except ImportError:
                logger.info("python-docx not installed; cannot preview .docx files.")
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "python-docx not installed."}
            except Exception as e:
                logger.warning(f"Failed to read DOCX file: {e}")
                return {"type": "binary", "name": file_name, "size": file_size, "reason": f"Failed to parse DOCX: {e}"}

        # ── XLSX ──
        if ext in XLSX_EXTENSIONS:
            if file_size > MAX_BINARY_BYTES:
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "Spreadsheet too large to preview."}
            try:
                from openpyxl import load_workbook
                wb = load_workbook(str(target), read_only=True, data_only=True)
                sheets_html = []
                for sheet_name in wb.sheetnames[:5]:  # limit to 5 sheets
                    ws = wb[sheet_name]
                    rows = list(ws.iter_rows(max_row=200, values_only=True))  # limit to 200 rows
                    if not rows:
                        continue
                    html = f"<h3>{sheet_name}</h3><table>"
                    for i, row in enumerate(rows):
                        tag = "th" if i == 0 else "td"
                        html += "<tr>" + "".join(f"<{tag}>{cell if cell is not None else ''}</{tag}>" for cell in row) + "</tr>"
                    html += "</table>"
                    sheets_html.append(html)
                wb.close()
                return {
                    "type": "spreadsheet",
                    "content": "\n".join(sheets_html),
                    "name": file_name,
                    "size": file_size,
                }
            except ImportError:
                logger.info("openpyxl not installed; cannot preview .xlsx files.")
                return {"type": "binary", "name": file_name, "size": file_size, "reason": "openpyxl not installed."}
            except Exception as e:
                logger.warning(f"Failed to read XLSX file: {e}")
                return {"type": "binary", "name": file_name, "size": file_size, "reason": f"Failed to parse XLSX: {e}"}

        # ── Fallback: attempt text read for extensionless or unknown files ──
        try:
            if file_size <= MAX_TEXT_BYTES:
                content = target.read_text(encoding="utf-8", errors="strict")
                # If it read cleanly as UTF-8, treat it as text
                return {"type": "text", "content": content, "name": file_name, "size": file_size}
        except (UnicodeDecodeError, ValueError):
            pass

        # ── Binary fallback ──
        return {"type": "binary", "name": file_name, "size": file_size}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

