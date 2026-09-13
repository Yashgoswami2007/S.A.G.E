import os
import re
from typing import List, Dict, Any, Optional

class DocumentChunker:
    """
    Splits documents (text, markdown, PDF, DOCX) into semantically coherent chunks
    while preserving structural metadata such as filename, page number, and section headings.
    """

    def __init__(self, chunk_size: int = 500, overlap: int = 60):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        source_name: str = "document.txt"
    ) -> List[Dict[str, Any]]:
        """
        Splits raw text or markdown into chunks respecting paragraph and line breaks.
        """
        metadata = metadata or {}
        base_meta = {
            "source": source_name,
            "filename": os.path.basename(source_name),
            "page": metadata.get("page", 1),
            **metadata
        }

        # Normalize newlines
        text = text.replace("\r\n", "\n")
        paragraphs = re.split(r'\n\s*\n', text)
        
        chunks: List[Dict[str, Any]] = []
        current_words: List[str] = []
        current_section = "General"

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Detect markdown headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', para)
            if heading_match:
                current_section = heading_match.group(2).strip()

            words = para.split()
            if not words:
                continue

            if len(current_words) + len(words) <= self.chunk_size:
                current_words.extend(words)
            else:
                if current_words:
                    chunk_text = " ".join(current_words)
                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            **base_meta,
                            "section": current_section,
                            "chunk_index": len(chunks)
                        }
                    })
                    # Keep overlap from the end of current words
                    overlap_words = current_words[-self.overlap:] if self.overlap < len(current_words) else current_words
                    current_words = list(overlap_words)
                
                # If a single paragraph is larger than chunk_size, slice it
                while len(words) > self.chunk_size:
                    slice_words = words[:self.chunk_size]
                    current_words.extend(slice_words)
                    chunks.append({
                        "text": " ".join(current_words),
                        "metadata": {
                            **base_meta,
                            "section": current_section,
                            "chunk_index": len(chunks)
                        }
                    })
                    current_words = slice_words[-self.overlap:] if self.overlap < len(slice_words) else slice_words
                    words = words[self.chunk_size:]

                current_words.extend(words)

        if current_words:
            chunks.append({
                "text": " ".join(current_words),
                "metadata": {
                    **base_meta,
                    "section": current_section,
                    "chunk_index": len(chunks)
                }
            })

        return chunks

    def chunk_pdf(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extracts and chunks pages from a PDF document using PyMuPDF (fitz) if available.
        """
        try:
            # pyrefly: ignore [missing-import]
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            chunks: List[Dict[str, Any]] = []
            
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_text = page.get_text("text")
                if not page_text.strip():
                    continue

                page_chunks = self.chunk_text(
                    text=page_text,
                    metadata={"page": page_index + 1},
                    source_name=file_path
                )
                chunks.extend(page_chunks)
            doc.close()
            return chunks
        except ImportError:
            # Fallback if PyMuPDF is not installed: read as raw text
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.chunk_text(content, source_name=file_path)

    def chunk_docx(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extracts and chunks paragraphs and tables from a DOCX document using python-docx if available.
        """
        try:
            # pyrefly: ignore [missing-import]
            import docx
            doc = docx.Document(file_path)
            full_text = []
            for p in doc.paragraphs:
                if p.text.strip():
                    full_text.append(p.text.strip())
            
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        full_text.append(row_text)
            
            combined_text = "\n\n".join(full_text)
            return self.chunk_text(combined_text, source_name=file_path)
        except ImportError:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.chunk_text(content, source_name=file_path)

    def chunk_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Dispatches to the appropriate chunker based on file extension.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self.chunk_pdf(file_path)
        elif ext in [".docx", ".doc"]:
            return self.chunk_docx(file_path)
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.chunk_text(content, source_name=file_path)
