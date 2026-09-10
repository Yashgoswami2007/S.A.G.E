"""
SAGE Document Generator Tools — generate_docx, generate_xlsx, generate_pptx, generate_pdf.

Create deliverable files (Word, Excel, PowerPoint, PDF) from structured data.
All are MODIFY permission (creates files in the workspace).
"""

import io
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.config import settings

logger = logging.getLogger("sage.tools.document_generators")
def _resolve_path(path_str: str) -> Path:
    """Resolves relative paths against workspace directory and enforces containment."""
    base_dir = Path(settings.WORKSPACE_DIR).resolve()
    target_path = (base_dir / path_str).resolve()

    try:
        target_path.relative_to(base_dir)
    except ValueError:
        if not str(target_path).startswith(str(base_dir)):
            return base_dir
    return target_path

def _output_path(filename: str, output_dir: Optional[str] = None) -> Path:
    """Resolve output path within the workspace."""
    base_dir = Path(settings.WORKSPACE_DIR).resolve()
    if output_dir:
        out_dir = (base_dir / output_dir).resolve()
    else:
        out_dir = base_dir / "output"

    # Containment check
    try:
        out_dir.relative_to(base_dir)
    except ValueError:
        out_dir = base_dir / "output"

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / filename


class GenerateDocxTool(BaseTool):
    """Generate a Word document (.docx) with the given title, sections, and content."""

    name = "generate_docx"
    description = (
        "Generate a Word document (.docx) with a title and content sections. "
        "Each section can have a heading and body text. "
        "The document is saved to the workspace output directory."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename (e.g. 'report.docx')",
            },
            "title": {
                "type": "string",
                "description": "Document title",
            },
            "sections": {
                "type": "array",
                "description": "List of sections, each with 'heading' and 'content' keys",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "output_dir": {
                "type": "string",
                "description": "Optional output subdirectory within workspace. Default: 'output'",
                "default": None,
            },
        },
        "required": ["filename", "title", "sections"],
    }

    async def execute(
        self,
        filename: str,
        title: str,
        sections: List[Dict[str, str]],
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        if not filename.endswith(".docx"):
            filename += ".docx"

        out_path = _output_path(filename, output_dir)

        try:
            from docx import Document
            from docx.shared import Pt

            doc = Document()

            # Title
            doc.add_heading(title, level=0)

            # Sections
            for section in sections:
                heading = section.get("heading", "")
                content = section.get("content", "")
                if heading:
                    doc.add_heading(heading, level=1)
                if content:
                    for paragraph in content.split("\n"):
                        if paragraph.strip():
                            doc.add_paragraph(paragraph.strip())

            doc.save(str(out_path))

            rel_path = str(out_path.relative_to(Path(settings.WORKSPACE_DIR).resolve()))
            return ToolResult(
                success=True,
                output=f"Word document created: {rel_path} ({out_path.stat().st_size} bytes)",
                data={"path": rel_path, "size_bytes": out_path.stat().st_size},
            )

        except ImportError:
            return ToolResult(
                success=False, output="",
                error="python-docx is not installed. Run: pip install python-docx",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to generate DOCX: {str(e)}")


class GenerateXlsxTool(BaseTool):
    """Generate an Excel spreadsheet (.xlsx) with headers and data rows."""

    name = "generate_xlsx"
    description = (
        "Generate an Excel spreadsheet (.xlsx) with one or more sheets. "
        "Each sheet has a name, headers, and data rows. "
        "The spreadsheet is saved to the workspace output directory."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename (e.g. 'data.xlsx')",
            },
            "sheets": {
                "type": "array",
                "description": "List of sheets, each with 'name', 'headers' (list of strings), and 'rows' (list of lists)",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array"}},
                    },
                },
            },
            "output_dir": {
                "type": "string",
                "description": "Optional output subdirectory. Default: 'output'",
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
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"

        out_path = _output_path(filename, output_dir)

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            wb = Workbook()
            # Remove default sheet
            wb.remove(wb.active)

            for sheet_data in sheets:
                sheet_name = sheet_data.get("name", "Sheet1")
                headers = sheet_data.get("headers", [])
                rows = sheet_data.get("rows", [])

                ws = wb.create_sheet(title=sheet_name)

                # Write headers with bold font
                if headers:
                    for col_idx, header in enumerate(headers, 1):
                        cell = ws.cell(row=1, column=col_idx, value=header)
                        cell.font = Font(bold=True)

                # Write data rows
                start_row = 2 if headers else 1
                for row_idx, row in enumerate(rows, start_row):
                    for col_idx, value in enumerate(row, 1):
                        ws.cell(row=row_idx, column=col_idx, value=value)

            wb.save(str(out_path))

            rel_path = str(out_path.relative_to(Path(settings.WORKSPACE_DIR).resolve()))
            return ToolResult(
                success=True,
                output=f"Excel spreadsheet created: {rel_path} ({out_path.stat().st_size} bytes)",
                data={"path": rel_path, "size_bytes": out_path.stat().st_size},
            )

        except ImportError:
            return ToolResult(
                success=False, output="",
                error="openpyxl is not installed. Run: pip install openpyxl",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to generate XLSX: {str(e)}")


class GeneratePptxTool(BaseTool):
    """Generate a PowerPoint presentation (.pptx) with title and content slides."""

    name = "generate_pptx"
    description = (
        "Generate a PowerPoint presentation (.pptx) with a title slide "
        "and content slides. Each slide can have a title, content text, "
        "and bullet points. The presentation is saved to the workspace output directory."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output filename (e.g. 'presentation.pptx')",
            },
            "title": {
                "type": "string",
                "description": "Presentation title (shown on the title slide)",
            },
            "subtitle": {
                "type": "string",
                "description": "Optional subtitle for the title slide",
            },
            "slides": {
                "type": "array",
                "description": "List of content slides, each with 'title', 'content' (body text), and optionally 'bullets' (list of strings)",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "output_dir": {
                "type": "string",
                "description": "Optional output subdirectory. Default: 'output'",
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
        if not filename.endswith(".pptx"):
            filename += ".pptx"

        out_path = _output_path(filename, output_dir)

        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt

            prs = Presentation()

            # Title slide
            title_layout = prs.slide_layouts[0]  # Title Slide layout
            title_slide = prs.slides.add_slide(title_layout)
            title_slide.shapes.title.text = title
            if subtitle and title_slide.placeholders[1]:
                title_slide.placeholders[1].text = subtitle

            # Content slides
            content_layout = prs.slide_layouts[1]  # Title and Content layout
            for slide_data in slides:
                slide = prs.slides.add_slide(content_layout)
                slide_title = slide_data.get("title", "")
                content = slide_data.get("content", "")
                bullets = slide_data.get("bullets", [])

                if slide_title:
                    slide.shapes.title.text = slide_title

                # Add content to the body placeholder
                body = slide.placeholders[1]
                tf = body.text_frame
                tf.clear()

                if content:
                    tf.text = content

                for bullet in bullets:
                    p = tf.add_paragraph()
                    p.text = bullet
                    p.level = 0

            prs.save(str(out_path))

            rel_path = str(out_path.relative_to(Path(settings.WORKSPACE_DIR).resolve()))
            return ToolResult(
                success=True,
                output=f"PowerPoint presentation created: {rel_path} ({out_path.stat().st_size} bytes, {len(slides) + 1} slides)",
                data={
                    "path": rel_path,
                    "size_bytes": out_path.stat().st_size,
                    "slide_count": len(slides) + 1,
                },
            )

        except ImportError:
            return ToolResult(
                success=False, output="",
                error="python-pptx is not installed. Run: pip install python-pptx",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to generate PPTX: {str(e)}")


def _validate_filename(filename: str) -> Optional[str]:
    """Validate that a filename is safe for writing. Returns error string or None if OK.

    Rejects empty filenames, path separators, parent-directory traversal, and
    absolute paths.  Does NOT reject any particular extension — callers handle
    extension normalisation themselves.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."
    if "/" in filename or "\\" in filename:
        return f"Filename must not contain path separators: '{filename}'"
    if ".." in filename:
        return f"Filename must not contain '..': '{filename}'"
    if os.path.isabs(filename):
        return f"Filename must not be an absolute path: '{filename}'"
    return None


def _pdf_html_template(body_html: str) -> str:
    """Wrap converted Markdown HTML in a styled document template for PDF rendering."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 12px;
        line-height: 1.6;
        color: #222;
        margin: 40px;
    }}
    h1 {{ font-size: 24px; margin-bottom: 8px; color: #111; }}
    h2 {{ font-size: 20px; margin-bottom: 6px; color: #222; }}
    h3 {{ font-size: 16px; margin-bottom: 4px; color: #333; }}
    h4 {{ font-size: 14px; margin-bottom: 4px; color: #444; }}
    p  {{ margin: 6px 0; }}
    ul, ol {{ margin: 6px 0 6px 20px; }}
    li {{ margin-bottom: 3px; }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 12px 0;
    }}
    th, td {{
        border: 1px solid #999;
        padding: 6px 10px;
        text-align: left;
    }}
    th {{
        background-color: #e8e8e8;
        font-weight: bold;
    }}
    pre {{
        background-color: #f4f4f4;
        border: 1px solid #ddd;
        padding: 10px;
        font-family: Courier, monospace;
        font-size: 11px;
        white-space: pre-wrap;
        word-wrap: break-word;
    }}
    code {{
        background-color: #f4f4f4;
        padding: 1px 4px;
        font-family: Courier, monospace;
        font-size: 11px;
    }}
    blockquote {{
        border-left: 3px solid #999;
        margin: 8px 0;
        padding: 4px 12px;
        color: #555;
    }}
    a {{ color: #1a5dad; text-decoration: underline; }}
    strong {{ font-weight: bold; }}
    em {{ font-style: italic; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


class GeneratePdfTool(BaseTool):
    """Generate a PDF document (.pdf) from Markdown content."""

    name = "generate_pdf"
    description = (
        "Create a PDF document from Markdown content and save it to the workspace. "
        "Use this tool to create, make, or generate PDF files, PDF reports, or "
        "formatted PDF documents. The content parameter accepts Markdown formatting "
        "including headings, bold, italic, lists, tables, code blocks, and blockquotes."
    )
    permission = ToolPermission.MODIFY
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Output PDF filename (e.g. 'report.pdf')",
            },
            "content": {
                "type": "string",
                "description": "Document content in Markdown format",
            },
            "output_dir": {
                "type": "string",
                "description": "Optional output subdirectory within workspace. Default: 'output'",
                "default": None,
            },
        },
        "required": ["filename", "content"],
    }

    async def execute(
        self,
        filename: str,
        content: str,
        output_dir: Optional[str] = None,
    ) -> ToolResult:
        # 1. Validate filename safety
        err = _validate_filename(filename)
        if err:
            return ToolResult(success=False, output="", error=err)

        # 2. Auto-append .pdf extension (case-insensitive)
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        out_path = _output_path(filename, output_dir)

        try:
            import markdown as md_lib
            from xhtml2pdf import pisa

            # Markdown → HTML
            html_body = md_lib.markdown(
                content,
                extensions=["tables", "fenced_code"],
            )

            # Wrap in styled template
            full_html = _pdf_html_template(html_body)

            # HTML → PDF
            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(io.StringIO(full_html), dest=pdf_buffer)

            if pisa_status.err:
                return ToolResult(
                    success=False, output="",
                    error=f"PDF rendering failed with {pisa_status.err} error(s).",
                )

            # Write to disk
            out_path.write_bytes(pdf_buffer.getvalue())

            rel_path = str(out_path.relative_to(Path(settings.WORKSPACE_DIR).resolve()))
            return ToolResult(
                success=True,
                output=f"PDF created successfully: {rel_path} ({out_path.stat().st_size} bytes)",
                data={"path": rel_path, "size_bytes": out_path.stat().st_size},
            )

        except ImportError:
            return ToolResult(
                success=False, output="",
                error="markdown or xhtml2pdf is not installed. Run: pip install markdown xhtml2pdf",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to generate PDF: {str(e)}")
