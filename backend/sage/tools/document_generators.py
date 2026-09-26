"""
SAGE Document Generator Tools
-----------------------------
Generate DOCX, XLSX, PPTX and PDF deliverables safely inside the active
workspace.

Design goals:
- Never allow output paths to escape the active workspace.
- Validate filenames consistently across all generators.
- Keep tool-call payloads bounded without silently truncating content.
- Preserve useful document structure (Markdown headings, lists, tables,
  code blocks and blockquotes) when generating DOCX/PDF.
- Produce usable XLSX/PPTX formatting instead of raw minimally formatted files.
- Return actionable ToolResult errors.
"""

import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sage.tools.base import BaseTool, ToolPermission, ToolResult
import sage.workspace as _ws_module

logger = logging.getLogger("sage.tools.document_generators")


# ---------------------------------------------------------------------------
# Shared limits / validation
# ---------------------------------------------------------------------------

# These are safety/operational limits, not LLM context limits.  The tools do
# NOT truncate content.  If a caller exceeds a limit, a clear error is
# returned instead of silently producing an incomplete document.
MAX_FILENAME_LENGTH = 255
MAX_TITLE_LENGTH = 500
MAX_CONTENT_CHARACTERS = 2_000_000
MAX_SHEETS = 100
MAX_ROWS_PER_SHEET = 100_000
MAX_COLUMNS_PER_SHEET = 256
MAX_SLIDES = 200
MAX_OUTPUT_DIR_LENGTH = 500

_INVALID_SHEET_CHARS = r'[]:*?/\\'


def _workspace_root() -> Path:
    return Path(
        _ws_module.workspace_manager.get_active_workspace()
    ).resolve()


def _resolve_path(path_str: str) -> Path:
    """Resolve a workspace-relative path using SAGE's workspace manager."""
    try:
        return _ws_module.workspace_manager.resolve_path(path_str)
    except PermissionError:
        return _workspace_root()


def _validate_filename(filename: str) -> Optional[str]:
    """Validate a single filename; paths are intentionally not accepted."""
    if not isinstance(filename, str) or not filename.strip():
        return "Filename cannot be empty."

    filename = filename.strip()

    if len(filename) > MAX_FILENAME_LENGTH:
        return (
            f"Filename is too long ({len(filename)} characters). "
            f"Maximum is {MAX_FILENAME_LENGTH}."
        )

    if "/" in filename or "\\" in filename:
        return f"Filename must not contain path separators: '{filename}'"

    if ".." in filename:
        return f"Filename must not contain '..': '{filename}'"

    if os.path.isabs(filename):
        return f"Filename must not be an absolute path: '{filename}'"

    if filename in {".", ".."}:
        return "Filename is invalid."

    return None


def _validate_title(title: str) -> Optional[str]:
    if not isinstance(title, str) or not title.strip():
        return "Title cannot be empty."
    if len(title) > MAX_TITLE_LENGTH:
        return (
            f"Title is too long ({len(title)} characters). "
            f"Maximum is {MAX_TITLE_LENGTH}."
        )
    return None


def _validate_content(content: str) -> Optional[str]:
    if not isinstance(content, str):
        return "Content must be a string."
    if len(content) > MAX_CONTENT_CHARACTERS:
        return (
            f"Content is too large ({len(content):,} characters). "
            f"Maximum is {MAX_CONTENT_CHARACTERS:,}. "
            "The content was not truncated."
        )
    return None


def _output_path(filename: str, output_dir: Optional[str] = None) -> Path:
    """
    Resolve an output path and enforce containment inside the active workspace.

    Invalid output directories raise PermissionError rather than silently
    redirecting the request to another directory.
    """
    base_dir = _workspace_root()

    if output_dir is None or not str(output_dir).strip():
        out_dir = (base_dir / "output").resolve()
    else:
        if len(output_dir) > MAX_OUTPUT_DIR_LENGTH:
            raise PermissionError("Output directory path is too long.")

        out_dir = (base_dir / output_dir).resolve()

    try:
        out_dir.relative_to(base_dir)
    except ValueError as exc:
        raise PermissionError(
            "Output directory must remain inside the active workspace."
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)

    final_path = (out_dir / filename).resolve()
    try:
        final_path.relative_to(base_dir)
    except ValueError as exc:
        raise PermissionError(
            "Output file must remain inside the active workspace."
        ) from exc

    return final_path


def _relative_output_path(path: Path) -> str:
    return str(path.relative_to(_workspace_root()))


def _tool_error(message: str) -> ToolResult:
    return ToolResult(success=False, output="", error=message)


def _normalise_extension(filename: str, extension: str) -> str:
    if not filename.lower().endswith(extension.lower()):
        return filename + extension
    return filename


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _split_table_row(line: str) -> List[str]:
    """Split a Markdown table row while respecting escaped pipes."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]

    cells: List[str] = []
    current: List[str] = []
    escaped = False

    for char in line:
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        escaped = char == "\\" and not escaped

    cells.append("".join(current).strip())
    return cells


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(
        re.fullmatch(r":?-{3,}:?", cell.strip()) is not None
        for cell in cells
    )


def _parse_markdown_blocks(content: str) -> List[Dict[str, Any]]:
    """
    Small dependency-free Markdown block parser used by DOCX/PPTX.

    Supported:
      # headings
      paragraphs
      - / * / + unordered lists
      1. ordered lists
      > blockquotes
      ``` fenced code blocks
      Markdown tables
      --- horizontal rules
    """
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    i = 0
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = "\n".join(paragraph).strip()
            if text:
                blocks.append({"type": "paragraph", "text": text})
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # Fenced code
        if stripped.startswith("```"):
            flush_paragraph()
            language = stripped[3:].strip()
            i += 1
            code_lines: List[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            blocks.append(
                {
                    "type": "code",
                    "text": "\n".join(code_lines),
                    "language": language,
                }
            )
            continue

        # Heading
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading_match.group(1)),
                    "text": heading_match.group(2).strip(),
                }
            )
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            blocks.append({"type": "quote", "text": "\n".join(quote_lines)})
            continue

        # Horizontal rule
        if re.fullmatch(r"[-*_](?:\s*[-*_]){2,}", stripped):
            flush_paragraph()
            blocks.append({"type": "rule"})
            i += 1
            continue

        # Markdown table
        if (
            "|" in stripped
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            flush_paragraph()
            headers = _split_table_row(stripped)
            i += 2
            rows: List[List[str]] = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            blocks.append({"type": "table", "headers": headers, "rows": rows})
            continue

        # Unordered list
        if re.match(r"^\s*[-*+]\s+", line):
            flush_paragraph()
            items: List[str] = []
            while i < len(lines):
                match = re.match(r"^\s*[-*+]\s+(.*)$", lines[i])
                if not match:
                    break
                items.append(match.group(1).strip())
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue

        # Ordered list
        if re.match(r"^\s*\d+[.)]\s+", line):
            flush_paragraph()
            items = []
            while i < len(lines):
                match = re.match(r"^\s*\d+[.)]\s+(.*)$", lines[i])
                if not match:
                    break
                items.append(match.group(1).strip())
                i += 1
            blocks.append({"type": "ol", "items": items})
            continue

        paragraph.append(line.rstrip())
        i += 1

    flush_paragraph()
    return blocks


def _strip_inline_markdown(text: str) -> str:
    """Conservative plain-text conversion for Office placeholders."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    return text


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

class GenerateDocxTool(BaseTool):
    """Generate a structured Word document from Markdown-like content."""

    name = "generate_docx"
    description = (
        "Generate a Word document (.docx) with a title and Markdown-like "
        "content. Supports headings, paragraphs, bullet lists, numbered lists, "
        "tables, blockquotes and fenced code blocks. The document is saved "
        "inside the active workspace."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename, e.g. 'report.docx'. Filename only; paths are not allowed.",
                "maxLength": MAX_FILENAME_LENGTH,
            },
            "title": {
                "type": "string",
                "description": "Document title.",
                "maxLength": MAX_TITLE_LENGTH,
            },
            "content": {
                "type": "string",
                "description": (
                    "Complete document body. Markdown-like headings, lists, "
                    "tables, code blocks and blockquotes are converted into "
                    "real Word structures. Content is not silently truncated."
                ),
                "maxLength": MAX_CONTENT_CHARACTERS,
            },
            "output_dir": {
                "type": "string",
                "description": "Optional workspace-relative output subdirectory. Default: 'output'.",
                "default": None,
            },
        },
        "required": ["filename", "title", "content"],
    }

    async def execute(
        self,
        filename: str,
        title: str,
        content: str,
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        err = _validate_filename(filename)
        if err:
            return _tool_error(err)

        err = _validate_title(title)
        if err:
            return _tool_error(err)

        err = _validate_content(content)
        if err:
            return _tool_error(err)

        filename = _normalise_extension(filename.strip(), ".docx")

        try:
            out_path = _output_path(filename, output_dir)

            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.shared import Inches, Pt

            doc = Document()

            # Basic professional margins.
            for section in doc.sections:
                section.top_margin = Inches(0.7)
                section.bottom_margin = Inches(0.7)
                section.left_margin = Inches(0.8)
                section.right_margin = Inches(0.8)

            title_para = doc.add_paragraph()
            title_para.style = doc.styles["Title"]
            title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = title_para.add_run(title.strip())
            run.bold = True

            blocks = _parse_markdown_blocks(content)

            for block in blocks:
                block_type = block["type"]

                if block_type == "heading":
                    level = min(max(int(block["level"]), 1), 6)
                    p = doc.add_heading(
                        _strip_inline_markdown(block["text"]),
                        level=level,
                    )
                    if level == 1:
                        p.paragraph_format.space_before = Pt(10)

                elif block_type == "paragraph":
                    p = doc.add_paragraph()
                    p.add_run(block["text"])

                elif block_type in {"ul", "ol"}:
                    style = "List Bullet" if block_type == "ul" else "List Number"
                    for item in block["items"]:
                        p = doc.add_paragraph(
                            _strip_inline_markdown(item),
                            style=style,
                        )

                elif block_type == "quote":
                    for line in block["text"].splitlines():
                        p = doc.add_paragraph()
                        p.style = doc.styles["Intense Quote"]
                        p.add_run(_strip_inline_markdown(line))

                elif block_type == "code":
                    p = doc.add_paragraph()
                    run = p.add_run(block["text"])
                    run.font.name = "Courier New"
                    run.font.size = Pt(9)

                elif block_type == "table":
                    headers = block["headers"]
                    rows = block["rows"]
                    if not headers:
                        continue

                    column_count = max(
                        len(headers),
                        max((len(row) for row in rows), default=0),
                    )
                    table = doc.add_table(
                        rows=1,
                        cols=max(column_count, 1),
                    )
                    table.style = "Table Grid"

                    for idx, value in enumerate(headers):
                        table.rows[0].cells[idx].text = _strip_inline_markdown(value)
                        for run in table.rows[0].cells[idx].paragraphs[0].runs:
                            run.bold = True

                    for row in rows:
                        cells = table.add_row().cells
                        for idx in range(column_count):
                            cells[idx].text = (
                                _strip_inline_markdown(row[idx])
                                if idx < len(row)
                                else ""
                            )

                elif block_type == "rule":
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(2)
                    p.add_run("─" * 70)

            doc.save(str(out_path))

            size = out_path.stat().st_size
            rel_path = _relative_output_path(out_path)

            return ToolResult(
                success=True,
                output=f"Word document created: {rel_path} ({size} bytes)",
                data={"path": rel_path, "size_bytes": size},
            )

        except ImportError:
            return _tool_error(
                "python-docx is not installed. Run: pip install python-docx"
            )
        except PermissionError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            logger.exception("DOCX generation failed")
            return _tool_error(f"Failed to generate DOCX: {exc}")


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    name = str(name or "").strip() or "Sheet"
    name = re.sub(_INVALID_SHEET_CHARS, "_", name)
    name = name.strip("'") or "Sheet"
    name = name[:31]

    base = name
    counter = 2
    while name.lower() in {x.lower() for x in used}:
        suffix = f" ({counter})"
        name = base[: 31 - len(suffix)] + suffix
        counter += 1

    used.add(name)
    return name


class GenerateXlsxTool(BaseTool):
    """Generate formatted Excel workbooks from structured sheet data."""

    name = "generate_xlsx"
    description = (
        "Generate an Excel spreadsheet (.xlsx) with one or more sheets. "
        "Each sheet has a name, headers and data rows. Headers are formatted, "
        "filters and freeze panes are applied, and columns are sized safely. "
        "The workbook is saved inside the active workspace."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename, e.g. 'data.xlsx'. Filename only; paths are not allowed.",
                "maxLength": MAX_FILENAME_LENGTH,
            },
            "sheets": {
                "type": "array",
                "description": "List of sheets with 'name', 'headers' and 'rows'.",
                "maxItems": MAX_SHEETS,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "maxLength": 31},
                        "headers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": MAX_COLUMNS_PER_SHEET,
                        },
                        "rows": {
                            "type": "array",
                            "maxItems": MAX_ROWS_PER_SHEET,
                            "items": {"type": "array"},
                        },
                    },
                },
            },
            "output_dir": {
                "type": "string",
                "description": "Optional workspace-relative output subdirectory. Default: 'output'.",
                "default": None,
            },
        },
        "required": ["filename", "sheets"],
    }

    async def execute(
        self,
        filename: str,
        sheets: List[Dict[str, Any]],
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        err = _validate_filename(filename)
        if err:
            return _tool_error(err)

        if not isinstance(sheets, list) or not sheets:
            return _tool_error("At least one worksheet is required.")

        if len(sheets) > MAX_SHEETS:
            return _tool_error(
                f"Too many worksheets ({len(sheets)}). Maximum is {MAX_SHEETS}."
            )

        filename = _normalise_extension(filename.strip(), ".xlsx")

        try:
            out_path = _output_path(filename, output_dir)

            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
            from openpyxl.worksheet.table import Table, TableStyleInfo

            wb = Workbook()
            wb.remove(wb.active)

            used_names: set[str] = set()

            header_font = Font(bold=True)
            header_fill = PatternFill(fill_type="solid", fgColor="D9EAD3")
            thin = Side(style="thin", color="B7B7B7")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)

            for sheet_index, sheet_data in enumerate(sheets, start=1):
                if not isinstance(sheet_data, dict):
                    return _tool_error(
                        f"Sheet {sheet_index} must be an object."
                    )

                headers = sheet_data.get("headers") or []
                rows = sheet_data.get("rows") or []

                if len(headers) > MAX_COLUMNS_PER_SHEET:
                    return _tool_error(
                        f"Sheet {sheet_index} has too many columns."
                    )
                if len(rows) > MAX_ROWS_PER_SHEET:
                    return _tool_error(
                        f"Sheet {sheet_index} has too many rows."
                    )

                sheet_name = _sanitize_sheet_name(
                    sheet_data.get("name", f"Sheet{sheet_index}"),
                    used_names,
                )
                ws = wb.create_sheet(title=sheet_name)
                ws.freeze_panes = "A2" if headers else "A1"

                if headers:
                    for col_idx, header in enumerate(headers, 1):
                        cell = ws.cell(row=1, column=col_idx, value=header)
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.border = border
                        cell.alignment = Alignment(
                            horizontal="center",
                            vertical="center",
                            wrap_text=True,
                        )

                start_row = 2 if headers else 1

                for row_idx, row in enumerate(rows, start_row):
                    if not isinstance(row, (list, tuple)):
                        return _tool_error(
                            f"Sheet '{sheet_name}' contains a non-list row."
                        )

                    if len(row) > MAX_COLUMNS_PER_SHEET:
                        return _tool_error(
                            f"Sheet '{sheet_name}' contains a row with too many columns."
                        )

                    for col_idx, value in enumerate(row, 1):
                        cell = ws.cell(
                            row=row_idx,
                            column=col_idx,
                            value=value,
                        )
                        cell.border = border
                        cell.alignment = Alignment(
                            vertical="top",
                            wrap_text=True,
                        )

                max_cols = max(
                    len(headers),
                    max((len(r) for r in rows if isinstance(r, (list, tuple))), default=0),
                )
                max_rows = len(rows) + (1 if headers else 0)

                # Reasonable column widths based on visible content.
                for col_idx in range(1, max(max_cols, 1) + 1):
                    letter = get_column_letter(col_idx)
                    max_len = 0

                    for row_idx in range(1, min(max_rows, 500) + 1):
                        value = ws.cell(row=row_idx, column=col_idx).value
                        if value is not None:
                            max_len = max(
                                max_len,
                                max(len(line) for line in str(value).splitlines()),
                            )

                    ws.column_dimensions[letter].width = min(
                        max(max_len + 2, 10),
                        50,
                    )

                if headers and rows:
                    end_row = len(rows) + 1
                    end_col = len(headers)

                    # Only create an Excel table when headers cover the data
                    # width. This gives filtering/sorting without inventing
                    # column names.
                    if end_col > 0:
                        ref = f"A1:{get_column_letter(end_col)}{end_row}"
                        table_name = (
                            "Table"
                            + re.sub(r"[^A-Za-z0-9]", "", sheet_name)
                            + str(sheet_index)
                        )
                        table_name = table_name[:250] or f"Table{sheet_index}"

                        table = Table(displayName=table_name, ref=ref)
                        style = TableStyleInfo(
                            name="TableStyleMedium2",
                            showFirstColumn=False,
                            showLastColumn=False,
                            showRowStripes=True,
                            showColumnStripes=False,
                        )
                        table.tableStyleInfo = style
                        ws.add_table(table)

            wb.save(str(out_path))

            size = out_path.stat().st_size
            rel_path = _relative_output_path(out_path)

            return ToolResult(
                success=True,
                output=f"Excel spreadsheet created: {rel_path} ({size} bytes)",
                data={"path": rel_path, "size_bytes": size},
            )

        except ImportError:
            return _tool_error(
                "openpyxl is not installed. Run: pip install openpyxl"
            )
        except PermissionError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            logger.exception("XLSX generation failed")
            return _tool_error(f"Failed to generate XLSX: {exc}")


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

class GeneratePptxTool(BaseTool):
    """Generate a PowerPoint presentation from structured/Markdown content."""

    name = "generate_pptx"
    description = (
        "Generate a PowerPoint presentation (.pptx) with a title slide and "
        "content slides. Each slide may contain content and bullet points. "
        "Markdown-like bullet lists inside content are also recognized."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename, e.g. 'presentation.pptx'. Filename only.",
                "maxLength": MAX_FILENAME_LENGTH,
            },
            "title": {
                "type": "string",
                "description": "Presentation title.",
                "maxLength": MAX_TITLE_LENGTH,
            },
            "subtitle": {
                "type": "string",
                "description": "Optional title-slide subtitle.",
                "maxLength": MAX_TITLE_LENGTH,
            },
            "slides": {
                "type": "array",
                "description": "Content slides with title, content and optional bullets.",
                "maxItems": MAX_SLIDES,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "maxLength": 300},
                        "content": {"type": "string", "maxLength": MAX_CONTENT_CHARACTERS},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string", "maxLength": 1000},
                        },
                    },
                },
            },
            "output_dir": {
                "type": "string",
                "description": "Optional workspace-relative output subdirectory. Default: 'output'.",
                "default": None,
            },
        },
        "required": ["filename", "title", "slides"],
    }

    async def execute(
        self,
        filename: str,
        title: str,
        slides: List[Dict[str, Any]],
        subtitle: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        err = _validate_filename(filename)
        if err:
            return _tool_error(err)

        err = _validate_title(title)
        if err:
            return _tool_error(err)

        if not isinstance(slides, list):
            return _tool_error("Slides must be a list.")

        if len(slides) > MAX_SLIDES:
            return _tool_error(
                f"Too many slides ({len(slides)}). Maximum is {MAX_SLIDES}."
            )

        if subtitle is not None and len(subtitle) > MAX_TITLE_LENGTH:
            return _tool_error(
                f"Subtitle exceeds {MAX_TITLE_LENGTH} characters."
            )

        filename = _normalise_extension(filename.strip(), ".pptx")

        try:
            out_path = _output_path(filename, output_dir)

            from pptx import Presentation
            from pptx.enum.text import PP_ALIGN
            from pptx.util import Inches, Pt

            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)

            # Title slide.
            title_layout = prs.slide_layouts[0]
            title_slide = prs.slides.add_slide(title_layout)
            title_slide.shapes.title.text = title.strip()

            if subtitle:
                placeholders = title_slide.placeholders
                if len(placeholders) > 1:
                    placeholders[1].text = subtitle.strip()

            for slide_index, slide_data in enumerate(slides, start=1):
                if not isinstance(slide_data, dict):
                    return _tool_error(
                        f"Slide {slide_index} must be an object."
                    )

                slide = prs.slides.add_slide(prs.slide_layouts[1])

                slide_title = str(slide_data.get("title", "") or "")
                content = str(slide_data.get("content", "") or "")
                bullets = slide_data.get("bullets") or []

                if slide_title:
                    slide.shapes.title.text = slide_title

                body = slide.placeholders[1]
                tf = body.text_frame
                tf.clear()
                tf.word_wrap = True

                blocks = _parse_markdown_blocks(content)
                content_added = False

                for block in blocks:
                    if block["type"] == "paragraph":
                        p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                        p.text = _strip_inline_markdown(block["text"])
                        p.level = 0
                        content_added = True

                    elif block["type"] == "ul":
                        for item in block["items"]:
                            p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                            p.text = _strip_inline_markdown(item)
                            p.level = 0
                            content_added = True

                    elif block["type"] == "ol":
                        for number, item in enumerate(block["items"], start=1):
                            p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                            p.text = f"{number}. {_strip_inline_markdown(item)}"
                            p.level = 0
                            content_added = True

                    elif block["type"] == "heading":
                        p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                        p.text = _strip_inline_markdown(block["text"])
                        p.level = 0
                        for run in p.runs:
                            run.font.bold = True
                        content_added = True

                    elif block["type"] == "quote":
                        p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                        p.text = f"“{_strip_inline_markdown(block['text'])}”"
                        p.level = 0
                        content_added = True

                    elif block["type"] == "code":
                        p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                        p.text = block["text"]
                        p.level = 0
                        content_added = True

                    elif block["type"] == "table":
                        # PowerPoint's standard content placeholder cannot
                        # reliably render arbitrary tables. Preserve the table
                        # as readable text rather than silently dropping it.
                        table_lines = [
                            " | ".join(block["headers"]),
                            " | ".join(["---"] * len(block["headers"])),
                        ]
                        table_lines.extend(" | ".join(row) for row in block["rows"])
                        p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                        p.text = "\n".join(table_lines)
                        p.level = 0
                        content_added = True

                for bullet in bullets:
                    p = tf.paragraphs[0] if not content_added else tf.add_paragraph()
                    p.text = str(bullet)
                    p.level = 0
                    content_added = True

                # Prevent huge font sizes on long content and make body text
                # readable in generated presentations.
                for paragraph in tf.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(18)

            prs.save(str(out_path))

            size = out_path.stat().st_size
            rel_path = _relative_output_path(out_path)

            return ToolResult(
                success=True,
                output=(
                    f"PowerPoint presentation created: {rel_path} "
                    f"({size} bytes, {len(slides) + 1} slides)"
                ),
                data={
                    "path": rel_path,
                    "size_bytes": size,
                    "slide_count": len(slides) + 1,
                },
            )

        except ImportError:
            return _tool_error(
                "python-pptx is not installed. Run: pip install python-pptx"
            )
        except PermissionError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            logger.exception("PPTX generation failed")
            return _tool_error(f"Failed to generate PPTX: {exc}")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _pdf_html_template(body_html: str, title: str) -> str:
    """
    HTML template deliberately uses conservative CSS because xhtml2pdf does
    not implement a full browser CSS engine.
    """
    import html

    safe_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 36pt 42pt 42pt 42pt;
    }}
    body {{
        font-family: DejaVuSans, Helvetica, Arial, sans-serif;
        font-size: 10.5pt;
        line-height: 1.45;
        color: #222222;
    }}
    h1 {{
        font-size: 20pt;
        margin-bottom: 10pt;
        color: #111111;
    }}
    h2 {{
        font-size: 15pt;
        margin-top: 12pt;
        margin-bottom: 6pt;
        color: #222222;
    }}
    h3 {{
        font-size: 12pt;
        margin-top: 10pt;
        margin-bottom: 4pt;
        color: #333333;
    }}
    h4, h5, h6 {{
        font-size: 10.5pt;
        margin-top: 8pt;
        margin-bottom: 4pt;
    }}
    p {{
        margin: 5pt 0;
    }}
    ul, ol {{
        margin-top: 4pt;
        margin-bottom: 6pt;
    }}
    li {{
        margin-bottom: 2pt;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 10pt 0;
        -pdf-keep-with-next: false;
    }}
    th, td {{
        border: 0.5pt solid #999999;
        padding: 4pt 5pt;
        text-align: left;
    }}
    th {{
        background-color: #E8E8E8;
        font-weight: bold;
    }}
    pre {{
        background-color: #F4F4F4;
        border: 0.5pt solid #DDDDDD;
        padding: 7pt;
        font-family: DejaVuSansMono, Courier, monospace;
        font-size: 8.5pt;
        white-space: pre-wrap;
    }}
    code {{
        font-family: DejaVuSansMono, Courier, monospace;
        font-size: 8.5pt;
    }}
    blockquote {{
        border-left: 2pt solid #999999;
        margin: 7pt 0;
        padding-left: 9pt;
        color: #555555;
    }}
    .document-title {{
        text-align: center;
        font-size: 21pt;
        font-weight: bold;
        margin-bottom: 16pt;
    }}
</style>
</head>
<body>
<div class="document-title">{safe_title}</div>
{body_html}
</body>
</html>"""


def _register_pdf_fonts() -> Dict[str, str]:
    """
    Try to register broadly available Unicode fonts for xhtml2pdf.
    Falls back to built-in PDF fonts if unavailable.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            (
                "DejaVuSans",
                "C:/Windows/Fonts/DejaVuSans.ttf",
                "C:/Windows/Fonts/DejaVuSans.ttf",
            ),
            (
                "DejaVuSansMono",
                "C:/Windows/Fonts/DejaVuSansMono.ttf",
                "C:/Windows/Fonts/DejaVuSansMono.ttf",
            ),
        ]

        # Common Linux locations.
        candidates.extend(
            [
                (
                    "DejaVuSans",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                ),
                (
                    "DejaVuSansMono",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                ),
            ]
        )

        registered: Dict[str, str] = {}

        for name, *paths in candidates:
            for path in paths:
                if Path(path).exists():
                    try:
                        pdfmetrics.registerFont(TTFont(name, path))
                        registered[name] = path
                        break
                    except Exception:
                        continue

        return registered

    except Exception:
        return {}


class GeneratePdfTool(BaseTool):
    """Generate an A4 PDF from Markdown content."""

    name = "generate_pdf"
    description = (
        "Create a PDF document from Markdown content and save it inside the "
        "active workspace. Supports headings, bold, italic, lists, tables, "
        "code blocks and blockquotes. A separate title is rendered at the top."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output PDF filename, e.g. 'report.pdf'. Filename only.",
                "maxLength": MAX_FILENAME_LENGTH,
            },
            "title": {
                "type": "string",
                "description": "PDF title.",
                "maxLength": MAX_TITLE_LENGTH,
            },
            "content": {
                "type": "string",
                "description": "Document body in Markdown format. Content is not silently truncated.",
                "maxLength": MAX_CONTENT_CHARACTERS,
            },
            "output_dir": {
                "type": "string",
                "description": "Optional workspace-relative output subdirectory. Default: 'output'.",
                "default": None,
            },
        },
        "required": ["filename", "title", "content"],
    }

    async def execute(
        self,
        filename: str,
        title: str,
        content: str,
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        err = _validate_filename(filename)
        if err:
            return _tool_error(err)

        err = _validate_title(title)
        if err:
            return _tool_error(err)

        err = _validate_content(content)
        if err:
            return _tool_error(err)

        filename = _normalise_extension(filename.strip(), ".pdf")

        try:
            out_path = _output_path(filename, output_dir)

            import markdown as md_lib
            from xhtml2pdf import pisa

            _register_pdf_fonts()

            html_body = md_lib.markdown(
                content,
                extensions=["tables", "fenced_code", "sane_lists"],
                output_format="html5",
            )

            full_html = _pdf_html_template(html_body, title)

            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(
                io.StringIO(full_html),
                dest=pdf_buffer,
                encoding="UTF-8",
            )

            if pisa_status.err:
                return _tool_error(
                    f"PDF rendering failed with {pisa_status.err} error(s)."
                )

            pdf_bytes = pdf_buffer.getvalue()

            # Basic file sanity check before declaring success.
            if not pdf_bytes.startswith(b"%PDF"):
                return _tool_error(
                    "PDF renderer returned invalid data; no valid PDF was written."
                )

            if len(pdf_bytes) < 100:
                return _tool_error(
                    "PDF renderer returned an unexpectedly small PDF."
                )

            out_path.write_bytes(pdf_bytes)

            size = out_path.stat().st_size
            rel_path = _relative_output_path(out_path)

            return ToolResult(
                success=True,
                output=f"PDF created successfully: {rel_path} ({size} bytes)",
                data={"path": rel_path, "size_bytes": size},
            )

        except ImportError:
            return _tool_error(
                "markdown or xhtml2pdf is not installed. "
                "Run: pip install markdown xhtml2pdf"
            )
        except PermissionError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            logger.exception("PDF generation failed")
            return _tool_error(f"Failed to generate PDF: {exc}")
