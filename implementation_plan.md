# SAGE — Full Agent Capability Implementation Plan

**Date:** 2026-09-02 | **Version:** 3.0 (Final Combined)

---

## 1. Current State Audit

### ✅ What Works

| Component | Location | Status |
|-----------|----------|--------|
| ReAct executor loop | [`executor.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/executor.py) | PLAN → ACT → OBSERVE → REFLECT → DELIVER with retry + fallback |
| Model router | [`router.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/router.py) | Deterministic routing by capability/keyword/modality |
| Model registry + lifecycle | [`lifecycle.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/models/lifecycle.py) | VRAM swap, fallback chains, circuit breaker, health checks |
| 7 core tools | [`tools/`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/tools) | `read_file`, `write_file`, `list_dir`, `search_files`, `get_file_info`, `apply_patch`, `execute_command` |
| 4 agent profiles | [`profiles/manager.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/profiles/manager.py) | `general`, `analyst`, `coder`, `inspector` |
| LLM-based planner | [`planner.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/planner.py) | Generates JSON step plans from prompts |
| Frontend chat UI | [`frontend/src/`](file:///c:/Users/HP/Downloads/SAGE/frontend/src) | Streaming, file upload, model/style selectors, sidebar |
| Audit logging | [`audit/logger.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/audit/logger.py) | Structured JSON via structlog |
| OpenAI-compatible client | [`client.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/models/client.py) | Chat + streaming + circuit breaker |

### ❌ Stub / Empty Modules

| Module | Has | Needs |
|--------|-----|-------|
| `sage/multimodal/` | Empty `__init__.py` | OCR engine, vision processor, image utils |
| `sage/rag/` | Empty `__init__.py` | Embedder, vector store, chunker, retriever |
| `sage/sandbox/` | Empty `__init__.py` | Docker sandbox manager, security policies |
| `sage/docgen/` | Empty `__init__.py` | Template engine, Word/Excel/PPT generators |
| `workspace/` | Empty dir | Agent working directory for file ops |
| `templates/` | Empty dir | Jinja2 document templates |

### 🚨 Critical Gap

The frontend's [`chat.ts`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/routes/api/chat.ts) talks **directly** to llama-server at `http://127.0.0.1:8001` — **bypassing the entire agent system**. The ReAct executor, tools, planner, router, and profiles are **never invoked** from the UI. This is the #1 thing to fix.

---

## 2. Architecture Overview

```
  Frontend (TanStack/React)
       │
       │  POST /api/chat  (structured SSE stream)
       ▼
  ┌─────────────────────────────────────────────────────┐
  │              FastAPI Backend (:8000)                 │
  │                                                     │
  │   /api/chat/stream ──► ReActExecutor                │
  │        │                    │                        │
  │        │              ┌─────▼──────┐                │
  │        │              │  Planner   │ (LLM plans)    │
  │        │              └─────┬──────┘                │
  │        │                    │                        │
  │   SSE  │    ┌───────────────▼───────────────┐       │
  │ events │    │        Tool Registry          │       │
  │   ◄────┤    │  ┌──────┬──────┬──────┬────┐  │       │
  │        │    │  │file  │doc   │ocr   │rag │  │       │
  │        │    │  │ops   │ops   │ops   │ops │  │       │
  │        │    │  ├──────┼──────┼──────┼────┤  │       │
  │        │    │  │code  │calc  │vision│user│  │       │
  │        │    │  │ops   │ops   │ops   │path│  │       │
  │        │    │  └──────┴──────┴──────┴────┘  │       │
  │        │    └───────────────────────────────┘       │
  │        │                    │                        │
  │        │              ┌─────▼──────┐                │
  │        │              │Model Router│                │
  │        │              └─────┬──────┘                │
  │        │                    ▼                        │
  │        │         llama-server instances              │
  │        │         :8001 (reasoning)                  │
  │        │         :8002 (vision/coding)              │
  └────────┴────────────────────────────────────────────┘
```

---

## 3. The Five Layers

---

### Layer 1 — Core Pipeline: Frontend ↔ Agent via Structured SSE

> **Goal:** Replace the raw llama-server proxy with the real agent loop, and give the frontend rich, typed events.

#### 1.1 Structured Event Protocol

Every SSE line the backend sends is a JSON object with a `type` field. The frontend renders each type with a dedicated UI widget.

```typescript
// frontend/src/lib/agent-events.ts

type AgentEvent =
  | { type: "PLAN_CREATED";         plan: { summary: string; steps: PlanStep[] } }
  | { type: "TOOL_CALL";            step_id: number; tool_name: string; tool_args: Record<string, any> }
  | { type: "TOOL_RESULT";          step_id: number; tool_name: string; success: boolean; output: string; error?: string }
  | { type: "THINKING";             content: string }
  | { type: "FILE_CREATED";         path: string; size_bytes: number }
  | { type: "FILE_MODIFIED";        path: string; diff_summary: string }
  | { type: "COMMAND_STARTED";      command: string; step_id: number }
  | { type: "COMMAND_FINISHED";     exit_code: number; stdout: string; stderr: string }
  | { type: "ERROR";                message: string; recoverable: boolean }
  | { type: "CONFIRMATION_REQUIRED"; action: string; description: string; request_id: string }
  | { type: "FINAL";                content: string }

type PlanStep = { id: number; description: string; tool?: string };
```

#### 1.2 Frontend Event Rendering

| Event | UI Widget |
|-------|-----------|
| `PLAN_CREATED` | Collapsible numbered step list with tool icons |
| `TOOL_CALL` | Inline chip `🔧 Reading report.pdf…` with spinner |
| `TOOL_RESULT` | Spinner → ✅/❌ badge, collapsible output preview |
| `THINKING` | Muted italic block (like current `<think>` block) |
| `FILE_CREATED` | Green pill `📄 Created: approval_note.docx (2.4 KB)` + download |
| `FILE_MODIFIED` | Yellow pill `✏️ Modified: data.xlsx` + diff summary |
| `COMMAND_STARTED` | Dark terminal block with command text + animated dots |
| `COMMAND_FINISHED` | Terminal block → exit code + stdout/stderr |
| `ERROR` | Red alert banner |
| `CONFIRMATION_REQUIRED` | Modal with Approve / Deny buttons — blocks agent |
| `FINAL` | Standard markdown (current assistant message style) |

#### 1.3 File Changes

##### [NEW] `backend/sage/api/events.py`
- Pydantic models for each `AgentEvent` variant
- `trace_to_event(TraceEvent) → AgentEvent` mapper — converts executor internals to frontend-facing events
- SSE serialization: `f"data: {event.model_dump_json()}\n\n"`

##### [MODIFY] [`chat.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/api/chat.py)
- Add `POST /stream` endpoint:
  - Accepts `{ prompt, profile, style, granted_paths, file_attachments }`
  - Runs `ReActExecutor.run()` with `stream_callback` that emits SSE events
  - State mapping: `PLANNING → PLAN_CREATED`, `ACTING → TOOL_CALL`, `OBSERVING → TOOL_RESULT`, etc.
  - `HIGH_RISK` tools → emit `CONFIRMATION_REQUIRED`, pause execution until frontend responds
  - LLM final output → `FINAL` event
- Add `POST /confirm` endpoint: receives `{ request_id, approved: bool }` to unblock pending confirmations

##### [MODIFY] [`chat.ts`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/routes/api/chat.ts)
- Change upstream from `http://127.0.0.1:8001/v1/chat/completions` → `http://127.0.0.1:8000/api/chat/stream`
- Pass through `profile`, `style`, `granted_paths`, `file_attachments`
- Forward structured SSE events as-is (remove delta/reasoning_content parsing)

##### [NEW] `frontend/src/lib/agent-events.ts`
- TypeScript types for all `AgentEvent` variants
- SSE line parser: `parseAgentEvent(line: string) → AgentEvent | null`

##### [NEW] `frontend/src/components/sage/AgentEventRenderer.tsx`
- Switch component: renders the right widget per event type
- Sub-components: `PlanCard`, `ToolCallChip`, `ToolResultCard`, `FileCreatedBadge`, `CommandBlock`, `ErrorBanner`, `ConfirmationDialog`

##### [MODIFY] [`Messages.tsx`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/components/sage/Messages.tsx)
- `ChatMessage` gains `events?: AgentEvent[]`
- Assistant messages render events in order via `AgentEventRenderer`
- `FINAL` event content becomes the main markdown body

##### [MODIFY] [`index.tsx`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/routes/index.tsx)
- Rewrite `run()`: parse SSE lines → accumulate `events[]` on assistant message
- Handle `CONFIRMATION_REQUIRED`: show modal, send approval/denial to `POST /api/chat/confirm`
- Auto-detect profile: images → `inspector`, code keywords → `coder`, else → `general`

##### [MODIFY] [`sage-store.ts`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/lib/sage-store.ts)
- Add `events?: AgentEvent[]` to `ChatMessage`
- Add `grantedPaths?: GrantedPath[]` to `Chat`
- Add `ServerAttachment` type (path-based, for server-side file references)

---

### Layer 2 — Permission-Based File Access

> **Goal:** The agent can read/write files on the user's machine, but *only* after the user explicitly grants a folder. The top bar shows access status.

#### 2.1 UX Flow

```
┌─────────────────────────────────────────────────────┐
│  DEFAULT STATE (header bar):                        │
│  🔒 No file access       [click to grant]           │
├─────────────────────────────────────────────────────┤
│                                                     │
│  USER CLICKS → "Grant Access" dialog opens:         │
│  ┌───────────────────────────────────────────────┐  │
│  │  Grant SAGE access to a folder                │  │
│  │                                               │  │
│  │  Path: [ C:\Users\HP\Documents\Reports     ]  │  │
│  │  Permission: ( ) Read Only  (•) Read & Write  │  │
│  │                                               │  │
│  │  [Validate Path]  →  ✅ Valid: 12 files       │  │
│  │                                               │  │
│  │              [Cancel]  [Grant Access]          │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
├─────────────────────────────────────────────────────┤
│  AFTER GRANT (header bar):                          │
│  📂 ...\Reports [R/W] [✕]  📂 ...\SOPs [R] [✕]    │
│                                                     │
│  ✕ = revoke access instantly                        │
├─────────────────────────────────────────────────────┤
│  AGENT-INITIATED REQUEST:                           │
│  Agent needs to save a file but has no write grant  │
│  → emits CONFIRMATION_REQUIRED event                │
│  → frontend shows grant dialog pre-filled           │
│  → user approves → agent continues                  │
└─────────────────────────────────────────────────────┘
```

#### 2.2 Data Model

```typescript
type GrantedPath = {
  id: string;
  path: string;                     // "C:\\Users\\HP\\Documents\\Reports"
  permission: "read" | "readwrite";
  grantedAt: number;
  label: string;                    // truncated display name: "...\Reports"
};
```

- Grants are **per-conversation** — stored in the `Chat` object in localStorage
- The backend receives `granted_paths[]` with every API call and validates against them
- The agent's system prompt lists granted paths so the LLM knows what's accessible

#### 2.3 Backend Enforcement

Every file tool call goes through a validation layer:
1. Is the target path under a granted path? → If not, return error + `CONFIRMATION_REQUIRED`
2. Does the grant have the right permission? (read vs readwrite) → If not, error
3. Path traversal check: resolved path must stay within the grant boundary

#### 2.4 File Changes

##### [NEW] `frontend/src/components/sage/AccessBar.tsx`
- Renders in the header between chat title and + button
- Default: `🔒 No file access` (clickable)
- Granted: pills showing `📂 path [permission] [✕]`

##### [NEW] `frontend/src/components/sage/GrantAccessDialog.tsx`
- Modal: path input + permission radio + validate + grant
- Calls `POST /api/files/validate-path` before granting
- Shows preview of folder contents after validation

##### [NEW] `backend/sage/api/files.py`
- `POST /validate-path` — checks path exists, is directory, returns file count & size
- `POST /browse` — directory listing at a granted path
- `POST /read` — reads file at granted path, dispatches to correct reader tool (PDF/DOCX/image/text)
- `POST /write` — writes file at granted path

##### [NEW] `backend/sage/tools/user_path_ops.py`
- `ReadUserPathTool` — reads from user-granted paths (`ToolPermission.HIGH_RISK`)
- `WriteUserPathTool` — writes to user-granted paths (`ToolPermission.HIGH_RISK`)
- `ListUserDirTool` — lists directory at user-granted paths (`ToolPermission.HIGH_RISK`)
- All validate against `granted_paths` passed in the request context

##### [MODIFY] [`main.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/main.py)
- `app.include_router(files.router, prefix="/api/files", tags=["files"])`

##### [MODIFY] [`index.tsx`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/routes/index.tsx)
- Add `AccessBar` to header
- Pass `grantedPaths` from chat state to every `/api/chat` call
- Wire grant/revoke actions to `updateChat()`

##### [MODIFY] [`sage-store.ts`](file:///c:/Users/HP/Downloads/SAGE/frontend/src/lib/sage-store.ts)
- `GrantedPath` type
- `grantedPaths: GrantedPath[]` on `Chat`
- `useGrantedPaths(chatId)` hook with localStorage persistence

---

### Layer 3 — Tool Arsenal (16 New Tools)

> **Goal:** Give the agent all the tools it needs to handle the 18 capability categories.

All tools extend `BaseTool`, use `ToolPermission`, and register in `create_default_tool_registry()`.

#### 3.1 Document Processing Tools

##### [NEW] `backend/sage/tools/document_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `read_pdf` | SAFE | Extract text + tables from PDF via `pymupdf` |
| `read_docx` | SAFE | Extract text + tables from DOCX via `python-docx` |
| `read_excel` | SAFE | Read Excel sheets → JSON/markdown table via `openpyxl` |
| `write_docx` | MODIFY | Generate Word doc from structured data + Jinja2 template |
| `write_excel` | MODIFY | Create/modify Excel with data, formulas, charts |
| `write_pptx` | MODIFY | Generate PowerPoint via `python-pptx` |

#### 3.2 OCR Tools

##### [NEW] `backend/sage/tools/ocr_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `ocr_image` | SAFE | Run Tesseract/EasyOCR on an image file → extracted text |
| `ocr_pdf` | SAFE | Rasterize scanned PDF pages (pymupdf) → OCR each page → combined text |

#### 3.3 Vision / Multimodal Tools

##### [NEW] `backend/sage/tools/vision_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `analyze_image` | SAFE | Send image to multimodal model (Gemma-4-12B) → visual QA response |
| `describe_diagram` | SAFE | Specialized prompt for P&IDs, engineering drawings, diagrams |

#### 3.4 RAG / Knowledge Base Tools

##### [NEW] `backend/sage/tools/rag_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `rag_search` | SAFE | Semantic search against local vector store → top-k chunks with citations |
| `rag_ingest` | MODIFY | Chunk + embed + index documents into vector store |

#### 3.5 Code Execution Tools

##### [NEW] `backend/sage/tools/code_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `execute_python` | HIGH_RISK | Run Python in subprocess sandbox with timeout, capture stdout/stderr |
| `execute_script` | HIGH_RISK | Run shell/bat scripts in isolated subprocess |

#### 3.6 Calculation Tools

##### [NEW] `backend/sage/tools/calc_ops.py`

| Tool | Permission | What it does |
|------|-----------|-------------|
| `calculate` | SAFE | Safe math evaluator (AST-based, no `eval`) — arithmetic, trig, engineering formulas |
| `spreadsheet_formula` | SAFE | Evaluate spreadsheet-style formulas (SUM, AVERAGE, VLOOKUP logic) |

#### 3.7 Registration

##### [MODIFY] [`tools/__init__.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/tools/__init__.py)
- Import all new tool classes
- Register all 23 tools (7 existing + 16 new) in `create_default_tool_registry()`

##### [MODIFY] [`pyproject.toml`](file:///c:/Users/HP/Downloads/SAGE/backend/pyproject.toml)
- Add dependencies:
  ```
  pymupdf>=1.24.0
  python-docx>=1.1.0
  openpyxl>=3.1.0
  python-pptx>=0.6.23
  pytesseract>=0.3.10
  Pillow>=10.0.0
  chromadb>=0.4.0
  sentence-transformers>=2.7.0
  jinja2>=3.1.0
  ```

---

### Layer 4 — Agent Intelligence Upgrades

> **Goal:** Make the planner tool-aware, the router smarter, the executor truly dynamic, and profiles comprehensive.

#### 4.1 Planner Upgrade

##### [MODIFY] [`planner.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/planner.py)
- **Tool-aware prompt**: System prompt lists all 23 tools with descriptions + parameter schemas
- **File-type awareness**: If prompt mentions "PDF" → plan includes `read_pdf`; "scanned" → `ocr_pdf` or `ocr_image`; "Excel" → `read_excel`
- **Workflow templates**: For common multi-step patterns, embed hints:

| Pattern | Workflow Steps |
|---------|---------------|
| **Inspection → Approval** | `ocr_pdf` → `rag_search` (SOP) → LLM reason → `write_docx` |
| **Coding Agent** | `write_file` → `execute_python` → inspect → fix → re-run → deliver |
| **Engineering Analysis** | `analyze_image` → `rag_search` → `calculate` → `write_docx` |
| **Spreadsheet Task** | `read_excel` → `calculate` → `write_excel` |
| **Document Summary** | `read_pdf`/`read_docx` → LLM summarize → `write_docx` |

#### 4.2 Router Expansion

##### [MODIFY] [`router.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/router.py)
- Expand keyword sets:

| Category | New Keywords |
|----------|-------------|
| OCR | `scan`, `ocr`, `handwritten`, `scanned`, `extract text from image` |
| Documents | `pdf`, `docx`, `word`, `excel`, `xlsx`, `spreadsheet`, `report`, `document` |
| Calculations | `calculate`, `formula`, `engineering calc`, `math`, `compute` |
| Vision | `drawing`, `p&id`, `photograph`, `inspect`, `diagram`, `blueprint` |

- Add file extension routing: `.pdf`/`.docx`/`.xlsx` → reasoning model; `.png`/`.jpg`/`.bmp` → vision model

#### 4.3 Profile Updates

##### [MODIFY] [`profiles/manager.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/profiles/manager.py)

| Profile | Max Permission | Tools |
|---------|---------------|-------|
| `general` | MODIFY | All 7 original + `read_pdf`, `read_docx`, `read_excel`, `rag_search`, `calculate`, `write_docx`, `write_excel` |
| `analyst` | SAFE | `read_file`, `list_dir`, `search_files`, `get_file_info`, `read_pdf`, `read_docx`, `read_excel`, `ocr_image`, `ocr_pdf`, `rag_search`, `rag_ingest`, `calculate`, `spreadsheet_formula` |
| `coder` | HIGH_RISK | All 7 original + `execute_python`, `execute_script`, `read_pdf`, `read_docx`, `calculate` |
| `inspector` | MODIFY | `read_file`, `list_dir`, `search_files`, `get_file_info`, `analyze_image`, `describe_diagram`, `ocr_image`, `ocr_pdf`, `rag_search`, `read_pdf`, `write_docx` |
| `documentor` (**NEW**) | MODIFY | All read tools + `write_docx`, `write_excel`, `write_pptx`, `rag_search`, `calculate`, `read_user_path`, `write_user_path` |

#### 4.4 Executor: True Dynamic ReAct

##### [MODIFY] [`executor.py`](file:///c:/Users/HP/Downloads/SAGE/backend/sage/agent/executor.py)

Current executor blindly follows the static plan. Upgrade to dynamic re-planning:

```
Current:  Plan → Execute step 1 → step 2 → step 3 → done
Upgraded: Plan → Execute step 1 → OBSERVE result → 
          ASK LLM: "Given this result, what should I do next?" →
          Execute step 2 → OBSERVE → re-evaluate → ...
```

Changes:
- **Dynamic re-planning**: After each OBSERVING step, pass tool results + history back to LLM → LLM decides next action (true ReAct) vs blindly following static plan
- **Tool result chaining**: Previous outputs become context for subsequent calls
- **Smart error recovery**: On failure → ask LLM for alternative approach instead of dumb retry
- **Structured event emission**: Map internal states to `AgentEvent` types:
  - After `write_file`/`write_docx` → emit `FILE_CREATED` / `FILE_MODIFIED`
  - Wrap `execute_command`/`execute_python` → emit `COMMAND_STARTED` then `COMMAND_FINISHED`
  - Tool with `HIGH_RISK` permission → emit `CONFIRMATION_REQUIRED`, await response

---

### Layer 5 — RAG Infrastructure & Document Generation

> **Goal:** Fill the empty `sage/rag/` and `sage/docgen/` modules with working implementations.

#### 5.1 RAG Pipeline

##### [NEW] `backend/sage/rag/embedder.py`
- Local embedding via `sentence-transformers` using `all-MiniLM-L6-v2` (~80MB, runs on CPU)
- `embed(text: str) → list[float]` — single text
- `embed_batch(texts: list[str]) → list[list[float]]` — batch for ingestion

##### [NEW] `backend/sage/rag/vector_store.py`
- ChromaDB persistent collection at `./workspace/vector_db/`
- `ingest(doc_id, chunks: list[Chunk])` — store chunks with metadata
- `search(query: str, top_k: int = 5) → list[SearchResult]` — returns chunks + scores + source citations
- Each `SearchResult` includes: `text`, `score`, `source_file`, `page_number`, `section_heading`

##### [NEW] `backend/sage/rag/chunker.py`
- Recursive paragraph/section splitter
- 512-token chunks, 64-token overlap
- Preserves metadata: page number, section heading, source file path
- Handles: plain text, PDF-extracted text, DOCX-extracted text

#### 5.2 Document Generation

##### [NEW] `backend/sage/docgen/generator.py`
- `generate_docx(template_name, data: dict) → Path` — renders Jinja2 template → Word file
- `generate_xlsx(sheets: list[SheetData]) → Path` — creates multi-sheet Excel
- `generate_pptx(slides: list[SlideData]) → Path` — creates PowerPoint

##### [NEW] `backend/sage/docgen/templates/`
- `approval_note.docx.j2` — standard MRPL-style approval note
- `inspection_report.docx.j2` — inspection findings → recommendation
- `technical_summary.docx.j2` — general-purpose technical summary

---

## 4. Capability Coverage Matrix

Every capability from the original 18-category list → mapped to implementation layer + tool.

| # | Capability | Layer | Tool(s) / Component |
|---|-----------|-------|-------------------|
| 1 | File Operations (PDF, DOCX, TXT, Excel, images) | L3 | `read_pdf`, `read_docx`, `read_excel`, `read_file`, `write_file`, `write_docx`, `write_excel` |
| 2 | Document Processing (summarize, extract, compare) | L3+L4 | Document tools + LLM reasoning via dynamic planner |
| 3 | OCR (scanned PDFs, photos, handwritten) | L3 | `ocr_image`, `ocr_pdf` |
| 4 | Vision / Multimodal (diagrams, P&IDs, photos) | L3 | `analyze_image`, `describe_diagram` |
| 5 | Local Knowledge Base / RAG | L5 | `rag_search`, `rag_ingest` + embedder + vector store |
| 6 | Code Generation | L4 | LLM + `write_file` via coder profile |
| 7 | Code Execution (sandbox, debug, re-run) | L3 | `execute_python`, `execute_script` |
| 8 | Spreadsheet Operations | L3 | `read_excel`, `write_excel`, `spreadsheet_formula` |
| 9 | Calculations | L3 | `calculate`, `spreadsheet_formula` |
| 10 | Document Generation (Word, PPT, Excel, PDF) | L3+L5 | `write_docx`, `write_excel`, `write_pptx` + docgen templates |
| 11 | Agentic Planning | L1+L4 | `Planner` + dynamic re-planning in executor |
| 12 | Tool Selection | L4 | Router keyword expansion + planner tool awareness |
| 13 | Iterative Execution | L4 | Dynamic ReAct loop with smart error recovery |
| 14 | Multi-Model Support | ✅ exists | Model registry + lifecycle manager |
| 15 | Automatic Model Routing | L4 | Router expansion (new keywords + file extension routing) |
| 16 | Local / Sovereign Operation | ✅ exists | Air-gap mode, local models, local embeddings, local vector DB |
| 17 | Security / Verification | L2 | Audit logging + permission grants + path validation |
| 18 | End-to-End Workflows | L4 | Workflow templates in planner |

---

## 5. Execution Order

```
Layer 1  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  (MUST be first)
  Wire frontend → agent, SSE protocol, event types, event renderers

Layer 2  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  (depends on L1 for CONFIRMATION_REQUIRED)
  Access bar, grant dialog, files API, user_path_ops tools

Layer 3  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  (independent of L2, can parallel)
  All 16 new tools: document, OCR, vision, RAG, code, calc

Layer 4  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  (depends on L3 tools existing)
  Planner upgrade, router expansion, profile updates, dynamic executor

Layer 5  ━━━━━━━━━━━━━━━━━━━━━━━━━  (depends on L3 rag_ops tool)
  Embedder, vector store, chunker, docgen templates
```

---

## 6. Open Questions

> [!WARNING]
> These need your answer before starting Layer 3.

1. **OCR engine**: Tesseract (needs `choco install tesseract`) vs EasyOCR (pip-installable, ~200MB download). Which?
2. **Vector DB**: ChromaDB (file-based, zero-config) vs pgvector (needs PostgreSQL running). ChromaDB OK for now?
3. **File size limit**: For server-side file reads via granted paths, suggested max 50MB. OK?

---

## 7. Verification Plan

### Per-Layer Smoke Tests

| Layer | Test |
|-------|------|
| L1 | Send "hello" → see `PLAN_CREATED` → `THINKING` → `FINAL` events render in chat |
| L1 | Trigger `execute_command` → see `CONFIRMATION_REQUIRED` modal → approve → see `COMMAND_STARTED` → `COMMAND_FINISHED` |
| L2 | Click 🔒 → grant `C:\Users\HP\Documents` → see badge → agent can `read_user_path` from it |
| L2 | Agent tries to write without grant → `CONFIRMATION_REQUIRED` → grant → write succeeds |
| L3 | Upload PDF → agent calls `read_pdf` → extracts text correctly |
| L3 | Upload scanned image → `ocr_image` → text extracted |
| L3 | Ask "run this Python code" → `execute_python` → `COMMAND_STARTED` + `COMMAND_FINISHED` |
| L4 | Ask "analyze this scanned inspection report and draft an approval note" → agent auto-chains: `ocr_pdf` → `rag_search` → LLM → `write_docx` |
| L5 | Ingest SOPs folder → ask a question → `rag_search` returns relevant chunks with citations |

### Automated Tests
```bash
cd backend && python -m pytest tests/ -v
```

### End-to-End Workflow Test
**Workflow A**: Scanned inspection report → OCR → RAG search SOPs → reasoning → approval note Word file
**Workflow B**: "Write Python to parse CSV and plot averages" → code gen → execute → fix errors → deliver working code
**Workflow C**: Engineering drawing photo → vision analysis → RAG search manuals → calculation → technical report
