"""
SAGE File Upload API — accepts multipart file uploads and saves to workspace.

Files are saved to WORKSPACE_DIR/uploads/<session_id>/ and their workspace-relative
paths are returned for use as file_attachments in the agent executor.
"""

import logging
import re
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, File, Form, UploadFile

from sage.config import settings

logger = logging.getLogger("sage.api.upload")

router = APIRouter()


def _sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal and invalid characters."""
    # Remove path separators and null bytes
    name = filename.replace("/", "_").replace("\\", "_").replace("\0", "")
    # Remove any leading dots (hidden files) or suspicious patterns
    name = name.lstrip(".")
    # Keep only safe characters
    name = re.sub(r'[^\w\s\-.]', '_', name)
    # Collapse multiple underscores/spaces
    name = re.sub(r'[_\s]+', '_', name).strip("_")
    return name or "unnamed_file"


@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    session_id: str = Form(default="default"),
) -> dict:
    """
    Accept multipart file uploads, save to workspace/uploads/<session_id>/,
    return workspace-relative paths for use as file_attachments.
    """
    try:
        workspace = Path(settings.WORKSPACE_DIR).resolve()
        upload_dir = Path(settings.UPLOAD_DIR).resolve() / session_id
        upload_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create upload directory: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to initialize upload directory: {str(e)}")

    saved_paths = []
    errors = []

    for file in files:
        try:
            safe_name = _sanitize_filename(file.filename or "unnamed_file")
            dest = upload_dir / safe_name

            # If file already exists, add a suffix
            counter = 1
            original_stem = dest.stem
            while dest.exists():
                dest = upload_dir / f"{original_stem}_{counter}{dest.suffix}"
                counter += 1

            # Read and save — no size limit
            content = await file.read()
            async with aiofiles.open(dest, "wb") as f:
                await f.write(content)

            # Return workspace-relative path
            try:
                rel_path = str(dest.relative_to(workspace))
            except ValueError:
                rel_path = str(dest.relative_to(upload_dir.parent.parent))

            saved_paths.append(rel_path)
            logger.info(
                "File uploaded: %s (%d bytes) -> %s",
                file.filename, len(content), rel_path,
            )

        except Exception as e:
            errors.append({"filename": file.filename, "error": str(e)})
            logger.error("Failed to upload %s: %s", file.filename, e)

    if not saved_paths and errors:
        from fastapi import HTTPException
        error_msg = "; ".join(f"{err['filename']}: {err['error']}" for err in errors)
        raise HTTPException(status_code=400, detail=f"Failed to upload files: {error_msg}")

    result = {"paths": saved_paths}
    if errors:
        result["errors"] = errors

    return result

