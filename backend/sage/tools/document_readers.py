"""
SAGE Document Reader Tools — read_pdf, read_docx, read_xlsx, read_image, ocr_extract.

Rich file readers that extract structured text from various document formats.
All are SAFE permission (read-only, no side effects). No file size limits.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.config import settings

logger = logging.getLogger("sage.tools.document_readers")


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


class ReadPDFTool(BaseTool):
    """Extract text content from a PDF file, including page-by-page text."""

    name = "read_pdf"
    description = (
        "Extract text content from a PDF file. Returns page-by-page text, "
        "page count, and document metadata. Works with both text-based and "
        "partially scanned PDFs. For fully scanned PDFs, use ocr_extract instead."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the PDF file in the workspace",
            },
            "pages": {
                "type": "string",
                "description": "Optional page range, e.g. '1-5' or '1,3,5'. Default: all pages",
                "default": None,
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str, pages: Optional[str] = None) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"PDF file not found: {path}")
            if not full_path.suffix.lower() == ".pdf":
                return ToolResult(success=False, output="", error=f"Not a PDF file: {path}")

            import fitz  # PyMuPDF

            doc = fitz.open(str(full_path))
            total_pages = len(doc)

            # Parse page range
            page_indices = list(range(total_pages))
            if pages:
                page_indices = _parse_page_range(pages, total_pages)

            text_parts = []
            for i in page_indices:
                page = doc[i]
                text = page.get_text("text")
                text_parts.append(f"--- Page {i + 1} ---\n{text.strip()}")

            metadata = doc.metadata or {}
            doc.close()

            output_parts = [
                f"File: {path}",
                f"Total pages: {total_pages}",
                f"Pages extracted: {len(page_indices)}",
            ]
            if metadata.get("title"):
                output_parts.append(f"Title: {metadata['title']}")
            if metadata.get("author"):
                output_parts.append(f"Author: {metadata['author']}")

            output_parts.append("")
            output_parts.extend(text_parts)

            return ToolResult(
                success=True,
                output="\n".join(output_parts),
                data={"total_pages": total_pages, "pages_extracted": len(page_indices)},
            )

        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="PyMuPDF (fitz) is not installed. Run: pip install PyMuPDF",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read PDF: {str(e)}")


class ReadDocxTool(BaseTool):
    """Extract text and tables from a Word document (.docx)."""

    name = "read_docx"
    description = (
        "Extract text and tables from a Word document (.docx). "
        "Returns paragraphs with heading levels and tables as structured text."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the .docx file in the workspace",
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"DOCX file not found: {path}")

            from docx import Document

            doc = Document(str(full_path))
            output_parts = [f"File: {path}", ""]

            # Extract paragraphs
            for para in doc.paragraphs:
                style = para.style.name if para.style else ""
                if "Heading" in style:
                    level = style.replace("Heading ", "").strip()
                    output_parts.append(f"{'#' * int(level)} {para.text}" if level.isdigit() else f"## {para.text}")
                elif para.text.strip():
                    output_parts.append(para.text)

            # Extract tables
            for idx, table in enumerate(doc.tables):
                output_parts.append(f"\n--- Table {idx + 1} ---")
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    output_parts.append(" | ".join(cells))

            return ToolResult(
                success=True,
                output="\n".join(output_parts),
                data={"paragraphs": len(doc.paragraphs), "tables": len(doc.tables)},
            )

        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="python-docx is not installed. Run: pip install python-docx",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read DOCX: {str(e)}")


class ReadXlsxTool(BaseTool):
    """Read data from an Excel spreadsheet (.xlsx)."""

    name = "read_xlsx"
    description = (
        "Read data from an Excel spreadsheet (.xlsx). Returns sheet names, "
        "headers, and row data in a structured text format. "
        "Can read specific sheets by name."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the .xlsx file in the workspace",
            },
            "sheet": {
                "type": "string",
                "description": "Optional sheet name to read. Default: first sheet",
            },
            "max_rows": {
                "type": "integer",
                "description": "Maximum number of rows to read. Default: all rows",
                "default": None,
            },
        },
        "required": ["path"],
    }

    async def execute(
        self, path: str, sheet: Optional[str] = None, max_rows: Optional[int] = None
    ) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"Excel file not found: {path}")

            from openpyxl import load_workbook

            wb = load_workbook(str(full_path), read_only=True, data_only=True)
            sheet_names = wb.sheetnames
            output_parts = [f"File: {path}", f"Sheets: {', '.join(sheet_names)}", ""]

            # Select sheet
            if sheet and sheet in sheet_names:
                ws = wb[sheet]
                sheets_to_read = [(sheet, ws)]
            elif sheet:
                wb.close()
                return ToolResult(
                    success=False, output="",
                    error=f"Sheet '{sheet}' not found. Available: {', '.join(sheet_names)}",
                )
            else:
                sheets_to_read = [(name, wb[name]) for name in sheet_names]

            for sheet_name, ws in sheets_to_read:
                output_parts.append(f"--- Sheet: {sheet_name} ---")
                row_count = 0
                for row in ws.iter_rows(values_only=True):
                    if max_rows and row_count >= max_rows:
                        output_parts.append(f"... (truncated at {max_rows} rows)")
                        break
                    cells = [str(c) if c is not None else "" for c in row]
                    output_parts.append(" | ".join(cells))
                    row_count += 1
                output_parts.append(f"({row_count} rows)")
                output_parts.append("")

            wb.close()
            return ToolResult(
                success=True,
                output="\n".join(output_parts),
                data={"sheets": sheet_names},
            )

        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="openpyxl is not installed. Run: pip install openpyxl",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read Excel: {str(e)}")


class ReadImageTool(BaseTool):
    """Get image metadata and basic information."""

    name = "read_image"
    description = (
        "Get image metadata and basic information (dimensions, format, color mode, EXIF data). "
        "Use this to understand an image before processing it further."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the image file in the workspace",
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"Image file not found: {path}")

            from PIL import Image, ExifTags

            img = Image.open(str(full_path))
            info = {
                "filename": full_path.name,
                "format": img.format or "Unknown",
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size_bytes": full_path.stat().st_size,
            }

            # Extract EXIF data if available
            exif_data = {}
            try:
                raw_exif = img._getexif()
                if raw_exif:
                    for tag_id, value in raw_exif.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                        if isinstance(value, (str, int, float)):
                            exif_data[tag_name] = value
            except (AttributeError, Exception):
                pass

            if exif_data:
                info["exif"] = exif_data

            img.close()

            output = json.dumps(info, indent=2, default=str)
            return ToolResult(success=True, output=output, data=info)

        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="Pillow is not installed. Run: pip install Pillow",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read image: {str(e)}")


class OCRExtractTool(BaseTool):
    """Extract text from scanned documents or images using OCR."""

    name = "ocr_extract"
    description = (
        "Extract text from scanned documents, photographs, or images using OCR (Tesseract). "
        "Supports PNG, JPG, BMP, TIFF, and scanned PDF files. "
        "For scanned PDFs, extracts text page-by-page."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the image or scanned PDF file",
            },
            "language": {
                "type": "string",
                "description": "OCR language code (e.g. 'eng', 'hin'). Default: 'eng'",
                "default": "eng",
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str, language: str = "eng") -> ToolResult:
        try:
            full_path = _resolve_path(path)
            if not full_path.exists() or not full_path.is_file():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            import pytesseract
            from PIL import Image

            ext = full_path.suffix.lower()

            if ext == ".pdf":
                # Scanned PDF: convert each page to image, then OCR
                return await self._ocr_pdf(full_path, language)
            else:
                # Direct image OCR
                img = Image.open(str(full_path))
                text = pytesseract.image_to_string(img, lang=language)
                img.close()

                return ToolResult(
                    success=True,
                    output=f"OCR result for {path}:\n\n{text.strip()}",
                    data={"chars_extracted": len(text.strip())},
                )

        except PermissionError as pe:
            return ToolResult(success=False, output="", error=f"Access Denied: {str(pe)}")
        except ImportError as ie:
            missing = str(ie)
            if "pytesseract" in missing:
                return ToolResult(
                    success=False, output="",
                    error="pytesseract is not installed. Run: pip install pytesseract",
                )
            elif "PIL" in missing:
                return ToolResult(
                    success=False, output="",
                    error="Pillow is not installed. Run: pip install Pillow",
                )
            return ToolResult(success=False, output="", error=f"Missing dependency: {missing}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"OCR failed: {str(e)}")


    async def _ocr_pdf(self, pdf_path: Path, language: str) -> ToolResult:
        """OCR a scanned PDF by converting pages to images first."""
        try:
            import fitz  # PyMuPDF
            import pytesseract
            from PIL import Image
            import io

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            text_parts = []

            for i in range(total_pages):
                page = doc[i]
                # Render page to image at 300 DPI
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))
                text = pytesseract.image_to_string(img, lang=language)
                text_parts.append(f"--- Page {i + 1} ---\n{text.strip()}")
                img.close()

            doc.close()

            output = f"OCR result for {pdf_path.name} ({total_pages} pages):\n\n"
            output += "\n\n".join(text_parts)

            return ToolResult(
                success=True,
                output=output,
                data={"total_pages": total_pages},
            )
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="PyMuPDF (fitz) is required for PDF OCR. Run: pip install PyMuPDF",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"PDF OCR failed: {str(e)}")


def _parse_page_range(pages_str: str, total_pages: int) -> list:
    """Parse a page range string like '1-5' or '1,3,5' into a list of 0-indexed page numbers."""
    indices = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start.strip()))
            end = min(total_pages, int(end.strip()))
            indices.extend(range(start - 1, end))
        else:
            page_num = int(part.strip())
            if 1 <= page_num <= total_pages:
                indices.append(page_num - 1)
    return sorted(set(indices))
