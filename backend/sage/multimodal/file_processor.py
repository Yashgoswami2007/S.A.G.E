"""
SAGE File Processor — extracts text and images from uploaded files
for injection into LLM messages.

Supports: PDF, DOCX, text/code files, images, spreadsheets.
"""

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("sage.multimodal.file_processor")

# Max characters to extract from any single file (fits within 8K context)
MAX_TEXT_CHARS = 20_000

# Extensions recognized as plain text / code
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".csv",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".sh", ".bat",
    ".ps1", ".rb", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".java",
    ".sql", ".html", ".css", ".scss", ".less", ".r", ".m", ".lua",
    ".dockerfile", ".makefile", ".env", ".gitignore",
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}

_SPREADSHEET_EXTENSIONS = {".xlsx", ".xls"}


@dataclass
class FileContent:
    """Result of processing a file for LLM consumption."""
    filename: str
    text: str = ""
    images: List[str] = field(default_factory=list)  # base64 data URIs
    file_type: str = "unknown"
    page_count: int = 0
    truncated: bool = False
    error: Optional[str] = None


class FileProcessor:
    """
    Extracts content from uploaded files for injection into LLM messages.
    All operations are synchronous (file I/O bound, not CPU heavy enough for async).
    """

    def __init__(self, max_chars: int = MAX_TEXT_CHARS):
        self.max_chars = max_chars

    def process(self, file_path: str) -> FileContent:
        """
        Process a file and extract its content.
        Routes to the appropriate extractor based on file extension.
        """
        path = Path(file_path)
        if not path.exists():
            return FileContent(
                filename=path.name,
                error=f"File not found: {file_path}",
            )

        ext = path.suffix.lower()
        filename = path.name

        try:
            if ext == ".pdf":
                return self._extract_pdf(path)
            elif ext == ".docx":
                return self._extract_docx(path)
            elif ext in _SPREADSHEET_EXTENSIONS:
                return self._extract_spreadsheet(path)
            elif ext in _IMAGE_EXTENSIONS:
                return self._extract_image(path)
            elif ext in _TEXT_EXTENSIONS or self._is_text_file(path):
                return self._extract_text(path)
            else:
                # Unknown type — return basic info
                size = path.stat().st_size
                return FileContent(
                    filename=filename,
                    text=f"[Attached file: {filename} ({self._format_size(size)})]",
                    file_type="binary",
                )
        except Exception as e:
            logger.error(f"Failed to process file {file_path}: {e}")
            return FileContent(
                filename=filename,
                text=f"[Failed to read file: {filename}]",
                error=str(e),
            )

    def process_multiple(self, file_paths: List[str]) -> List[FileContent]:
        """Process multiple files."""
        return [self.process(p) for p in file_paths]

    def build_context_string(self, contents: List[FileContent]) -> str:
        """
        Build a combined context string from multiple file contents
        for injection into the user prompt.
        """
        if not contents:
            return ""

        parts = []
        for fc in contents:
            if fc.error and not fc.text:
                parts.append(f"\n--- Attached: {fc.filename} ---\n[Error: {fc.error}]")
            elif fc.text:
                header = f"\n--- Attached: {fc.filename}"
                if fc.page_count > 0:
                    header += f" ({fc.page_count} pages)"
                if fc.truncated:
                    header += " [truncated]"
                header += " ---\n"
                parts.append(header + fc.text)

        return "\n".join(parts)

    def collect_images(self, contents: List[FileContent]) -> List[str]:
        """Collect all base64 image data URIs from processed files."""
        images = []
        for fc in contents:
            images.extend(fc.images)
        return images

    # ── Extractors ──────────────────────────────────────────────────────

    def _extract_pdf(self, path: Path) -> FileContent:
        """Extract text from PDF using PyMuPDF."""
        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf  # type: ignore[no-redef]
            except ImportError:
                return FileContent(
                    filename=path.name,
                    text=f"[PDF attached: {path.name} — PyMuPDF not installed for text extraction]",
                    file_type="pdf",
                    error="PyMuPDF not installed",
                )

        doc = pymupdf.open(str(path))
        page_count = len(doc)
        text_parts = []
        total_chars = 0

        for page_num in range(page_count):
            page = doc[page_num]
            page_text = page.get_text("text")
            if page_text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{page_text.strip()}")
                total_chars += len(page_text)
                if total_chars >= self.max_chars:
                    break

        doc.close()

        full_text = "\n\n".join(text_parts)
        truncated = len(full_text) > self.max_chars
        if truncated:
            full_text = full_text[: self.max_chars] + "\n[... content truncated ...]"

        if not full_text.strip():
            full_text = f"[PDF '{path.name}' contains no extractable text — may be scanned/image-based]"

        return FileContent(
            filename=path.name,
            text=full_text,
            file_type="pdf",
            page_count=page_count,
            truncated=truncated,
        )

    def _extract_docx(self, path: Path) -> FileContent:
        """Extract text from DOCX using python-docx."""
        try:
            from docx import Document
        except ImportError:
            return FileContent(
                filename=path.name,
                text=f"[DOCX attached: {path.name} — python-docx not installed]",
                file_type="docx",
                error="python-docx not installed",
            )

        doc = Document(str(path))
        paragraphs = []
        total_chars = 0

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
                total_chars += len(text)
                if total_chars >= self.max_chars:
                    break

        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                row_text = " | ".join(cells)
                if row_text.strip():
                    paragraphs.append(row_text)
                    total_chars += len(row_text)
                    if total_chars >= self.max_chars:
                        break

        full_text = "\n".join(paragraphs)
        truncated = len(full_text) > self.max_chars
        if truncated:
            full_text = full_text[: self.max_chars] + "\n[... content truncated ...]"

        return FileContent(
            filename=path.name,
            text=full_text or f"[DOCX '{path.name}' appears to be empty]",
            file_type="docx",
            truncated=truncated,
        )

    def _extract_text(self, path: Path) -> FileContent:
        """Read plain text / code files."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = path.read_bytes().decode("utf-8", errors="replace")

        truncated = len(content) > self.max_chars
        if truncated:
            content = content[: self.max_chars] + "\n[... content truncated ...]"

        return FileContent(
            filename=path.name,
            text=content,
            file_type="text",
            truncated=truncated,
        )

    def _extract_image(self, path: Path) -> FileContent:
        """Encode image as base64 data URI for vision models."""
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        data_uri = f"data:{mime};base64,{b64}"

        return FileContent(
            filename=path.name,
            text=f"[Image attached: {path.name} ({self._format_size(len(raw))})]",
            images=[data_uri],
            file_type="image",
        )

    def _extract_spreadsheet(self, path: Path) -> FileContent:
        """Extract first sheet as text table using openpyxl."""
        try:
            from openpyxl import load_workbook
        except ImportError:
            return FileContent(
                filename=path.name,
                text=f"[Spreadsheet attached: {path.name} — openpyxl not installed]",
                file_type="spreadsheet",
                error="openpyxl not installed",
            )

        wb = load_workbook(str(path), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            wb.close()
            return FileContent(
                filename=path.name,
                text=f"[Spreadsheet '{path.name}' has no active sheet]",
                file_type="spreadsheet",
            )

        rows = []
        total_chars = 0
        max_rows = 200  # limit rows for context

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            cells = [str(c) if c is not None else "" for c in row]
            row_text = " | ".join(cells)
            rows.append(row_text)
            total_chars += len(row_text)
            if total_chars >= self.max_chars:
                break

        wb.close()

        full_text = "\n".join(rows)
        truncated = len(full_text) > self.max_chars or i >= max_rows  # noqa: F821
        if truncated:
            full_text = full_text[: self.max_chars] + "\n[... rows truncated ...]"

        return FileContent(
            filename=path.name,
            text=full_text or f"[Spreadsheet '{path.name}' appears to be empty]",
            file_type="spreadsheet",
            truncated=truncated,
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _is_text_file(self, path: Path) -> bool:
        """Heuristic: try to read first 1KB as UTF-8."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
            chunk.decode("utf-8")
            return True
        except (UnicodeDecodeError, OSError):
            return False

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
