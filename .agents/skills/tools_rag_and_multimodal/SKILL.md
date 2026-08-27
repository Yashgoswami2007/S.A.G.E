---
name: sage_tools_rag_and_multimodal
description: Guides tool registration patterns, Docker sandbox execution, local pgvector RAG pipeline, Tesseract/PaddleOCR pipelines, and Jinja2-based document generators.
---
# SAGE — Section 3: Tools, RAG & Multimodal Pipeline

**SIH Problem Statement:** SIH26117 — Sovereign On-Premise Agentic AI Workbench  
**Sponsoring Organization:** Mangalore Refinery and Petrochemicals Limited (MRPL)  
**Date:** 2026-08-26

---

## 11. Tool/Plugin Architecture

### Tool Registry Pattern

Every tool in SAGE is a Python class that:
1. Declares its **schema** (name, description, parameters) — this is sent to the LLM for tool selection.
2. Implements an **execute** method.
3. Is **auto-discovered** by the registry at startup.

```python
from sage.tools.base import Tool, ToolResult, tool_param

class FileReadTool(Tool):
    name = "read_file"
    description = "Read the contents of a file at the given path"
    
    @tool_param("path", str, "Absolute path to the file to read")
    async def execute(self, path: str) -> ToolResult:
        # Sandboxed: path must be within allowed directories
        self.validate_path(path)
        content = await aiofiles.open(path).read()
        return ToolResult(success=True, output=content[:10000])
```

### Tool Catalog (MVP)

| Tool | Category | Description |
|------|----------|-------------|
| `read_file` | File I/O | Read file contents |
| `write_file` | File I/O | Write/create file |
| `list_directory` | File I/O | List directory contents |
| `execute_code` | Code Exec | Run Python/JS in sandbox |
| `run_shell` | Code Exec | Run shell command in sandbox |
| `rag_search` | Knowledge | Search local knowledge base |
| `ocr_extract` | Multimodal | Extract text from image/PDF |
| `vision_analyze` | Multimodal | Analyze image with vision model |
| `generate_word` | Doc Gen | Generate Word document from template |
| `generate_pptx` | Doc Gen | Generate PowerPoint presentation |
| `generate_xlsx` | Doc Gen | Generate Excel spreadsheet |
| `web_search_local` | Search | Search local document index (not internet) |
| `calculator` | Utility | Safe math expression evaluation |

### Adding New Tools

```python
# 1. Create a new file in sage/tools/
# 2. Implement the Tool base class
# 3. Register it in tools/__init__.py or use auto-discovery
# 4. The tool's schema is automatically exposed to the LLM
# No other changes needed.
```

---

## 12. Sandbox Architecture & Security

### Design: Docker-Based Isolation

```
┌───────────────────────────────────┐
│         SAGE Backend              │
│  ┌─────────────────────────┐      │
│  │   Code Execution Tool   │      │
│  │   ┌─────────────────┐   │      │
│  │   │  SandboxManager  │──┼──────┼──► Docker API
│  │   └─────────────────┘   │      │
│  └─────────────────────────┘      │
└───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│   Docker Container (ephemeral)     │
│   ┌──────────────────────────┐     │
│   │  Python 3.12 runtime     │     │
│   │  - No network access     │     │
│   │  - Read-only root FS     │     │
│   │  - /workspace mounted RW │     │
│   │  - 512MB memory limit    │     │
│   │  - 30s execution timeout │     │
│   │  - Non-root user         │     │
│   │  - seccomp profile       │     │
│   └──────────────────────────┘     │
└────────────────────────────────────┘
```

### Security Layers

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| 1 | **Docker isolation** | Separate PID/network/mount namespace |
| 2 | **Network disabled** | `--network=none` — no egress possible |
| 3 | **Resource limits** | `--memory=512m --cpus=1 --pids-limit=100` |
| 4 | **Timeout** | 30-second hard kill |
| 5 | **Read-only rootfs** | Cannot modify system binaries |
| 6 | **Non-root user** | Runs as `uid=1000` inside container |
| 7 | **Seccomp profile** | Blocks dangerous syscalls |
| 8 | **Path validation** | SAGE validates all file paths before passing to sandbox |

### Sandbox for SIH Demo (Simplified)

For the demo, use `subprocess` with:
- `timeout` enforced
- Restricted to a temporary directory
- No network (OS-level firewall rule on the subprocess)

Docker sandbox is for production.

---

## 13. Local RAG / Knowledge-Base Architecture

### Pipeline Architecture

```
   Documents (PDF, DOCX, TXT, images)
         │
         ▼
   ┌─────────────┐
   │   PARSER     │  ◄── Apache Tika / PyMuPDF / python-docx
   │  (extract    │      Convert to structured markdown
   │   structured │      Preserve tables, headings, sections
   │   content)   │
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   CHUNKER    │  ◄── Recursive character + semantic chunking
   │  (smart      │      Respect section boundaries
   │   splitting) │      Include metadata (source, page, section)
   └──────┬──────┘
          │
          ▼
   ┌──────────────┐
   │   EMBEDDER    │  ◄── BGE-M3 or nomic-embed-text (local)
   │  (vectorize)  │      Dense + sparse vectors
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │   pgvector    │  ◄── PostgreSQL extension
   │  (store)      │      Stores vectors + metadata + source text
   └──────────────┘
```

### Retrieval Strategy: Hybrid Search

```python
def hybrid_search(query: str, top_k: int = 5) -> list[Chunk]:
    # 1. Dense vector search (semantic similarity)
    dense_results = pgvector_search(embed(query), top_k=top_k * 2)
    
    # 2. BM25 keyword search (exact term matching)
    bm25_results = bm25_search(query, top_k=top_k * 2)
    
    # 3. Reciprocal Rank Fusion
    fused = reciprocal_rank_fusion(dense_results, bm25_results)
    
    # 4. Return top-k with source attribution
    return fused[:top_k]
```

### Why pgvector Over ChromaDB or Milvus?

| | pgvector | ChromaDB | Milvus |
|-|----------|----------|--------|
| **Operational overhead** | Zero (PostgreSQL extension) | Separate process | Full cluster |
| **ACID transactions** | ✅ | ❌ | ❌ |
| **Relational data** | Same DB | Separate DB needed | Separate DB needed |
| **Air-gap deployment** | ✅ Trivial | ✅ Easy | ⚠️ Complex |
| **Scale needed for SIH** | <100K docs → perfect | OK | Overkill |
| **BM25 support** | Via `pg_trgm` + `tsvector` | Plugin | Built-in |

### Document Ingestion

```
sage-admin ingest --source /path/to/SOPs/ --collection "sops"
sage-admin ingest --source /path/to/reports/ --collection "inspection_reports"
```

Each document gets:
- Parsed into structured text (preserving tables, headings)
- Split into chunks (512-1024 tokens, with overlap)
- Each chunk embedded and stored with metadata:
  - `source_file`, `page_number`, `section_heading`, `collection`, `ingested_at`

---

## 14. OCR & Multimodal Pipeline

### Pipeline Architecture

```
Input (image/scanned PDF)
       │
       ├──► Is it a scanned PDF?
       │    Yes ──► pdf2image (extract pages as images)
       │    No  ──► Use image directly
       │
       ▼
   ┌──────────────────────────────┐
   │   Stage 1: OCR              │
   │   Tesseract (fast, good     │
   │   for clean text)           │
   │   + PaddleOCR (better for   │
   │   complex layouts, tables)  │
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │   Stage 2: Vision LLM       │
   │   (If OCR alone insufficient)│
   │   Qwen2.5-VL-7B             │
   │   "Describe this engineering │
   │    drawing / P&ID / form"   │
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │   Stage 3: Structured       │
   │   Extraction                │
   │   LLM parses OCR + vision   │
   │   output into structured    │
   │   Pydantic schema           │
   └──────────────────────────────┘
```

### Why Two-Stage OCR?

1. **Tesseract** is fast and reliable for printed English text. Use it as the primary OCR.
2. **PaddleOCR** handles complex layouts (tables, multi-column, handwritten) better. Use it as fallback or for specific document types.
3. **Vision LLM** is the "understanding" layer — it doesn't just extract text; it *interprets* diagrams, P&IDs, and handwritten annotations.

### Handling Specific Document Types

| Document Type | OCR Strategy | Vision Strategy |
|--------------|-------------|-----------------|
| Printed form | Tesseract (sufficient) | Not needed |
| Scanned table | PaddleOCR (layout-aware) | Verify table structure |
| Handwritten notes | PaddleOCR + Vision LLM | LLM interprets handwriting |
| Engineering drawing | Minimal OCR (labels only) | Vision LLM describes components |
| P&ID | PaddleOCR for tags/labels | Vision LLM identifies flow/connections |

---

## 15. Document Generation Pipeline

### Schema-First Architecture

```
Agent Output (structured JSON/Pydantic)
       │
       ▼
   ┌──────────────────────────────┐
   │   Pydantic Validation        │
   │   Ensures all required       │
   │   fields are present         │
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │   Template Engine            │
   │   ┌────────────────────┐     │
   │   │ Word: docx-template│     │
   │   │ PPTX: python-pptx  │     │
   │   │ XLSX: openpyxl      │     │
   │   │ Code: direct write  │     │
   │   └────────────────────┘     │
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │   Output File                │
   │   Saved to /workspace/output │
   │   Served via API download    │
   └──────────────────────────────┘
```

### Word Document Generation

```python
# Template approach using python-docx-template
from docxtpl import DocxTemplate

class WordGenerator:
    def generate(self, template_name: str, data: dict, output_path: str):
        tpl = DocxTemplate(f"templates/{template_name}.docx")
        tpl.render(data)
        tpl.save(output_path)
```

**Template example (approval_note.docx):**
```
APPROVAL NOTE
Date: {{ date }}
Reference: {{ reference_number }}

Subject: {{ subject }}

Findings:
{% for finding in findings %}
  {{ loop.index }}. {{ finding.description }}
     Status: {{ finding.status }}
     SOP Reference: {{ finding.sop_ref }}
{% endfor %}

Recommendation: {{ recommendation }}

Prepared by: SAGE Agentic AI System
Reviewed by: ________________________
```

### Deliverable Types

| Type | Library | Template-Driven? | Notes |
|------|---------|-------------------|-------|
| Word (.docx) | `python-docx-template` | ✅ Yes | Jinja2 tags in .docx files |
| PowerPoint (.pptx) | `python-pptx` | ✅ Yes (master slides) | Builder pattern for slides |
| Excel (.xlsx) | `openpyxl` | ⚠️ Partial | Programmatic cell writing |
| Code files | Direct file write | ❌ | Agent writes code directly |
| PDF | `weasyprint` or `reportlab` | ✅ HTML→PDF | For formal reports |
