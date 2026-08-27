# SAGE — Section 5: Development Phases, Data Flow & Demo Strategy

**SIH Problem Statement:** SIH26117 — Sovereign On-Premise Agentic AI Workbench  
**Sponsoring Organization:** Mangalore Refinery and Petrochemicals Limited (MRPL)  
**Date:** 2026-08-26

---

## 22. Data Flow

### End-to-End Data Flow (Inspection Workflow)

```
User uploads scanned_report.pdf via UI
    │
    ▼
[1] API Gateway receives file
    │ Logged: file_upload, user_id, filename, size, hash
    │
    ▼
[2] Agent Engine starts execution
    │ State: PLANNING
    │ Model Router → selects vision model
    │
    ▼
[3] OCR Tool extracts text from PDF
    │ Tesseract + PaddleOCR → structured text
    │ Logged: tool_call, ocr_extract, latency
    │
    ▼
[4] Vision LLM analyzes images (if needed)
    │ Model Server (Qwen2.5-VL-7B) → description
    │ Logged: model_inference, tokens, latency
    │
    ▼
[5] RAG Search retrieves relevant SOPs
    │ Query → pgvector hybrid search → top-5 chunks
    │ Logged: tool_call, rag_search, query, results_count
    │
    ▼
[6] Reasoning LLM generates analysis
    │ Model Server (Qwen3-8B) → structured findings
    │ Logged: model_inference, tokens, latency
    │
    ▼
[7] Document Generator creates Word file
    │ Pydantic validation → docx-template render
    │ Logged: tool_call, generate_word, output_path
    │
    ▼
[8] Output delivered to user
    │ File stored in /workspace/outputs/
    │ User can download via UI
    │ Logged: file_download, user_id, doc_id
```

**Every single step is logged. No data leaves the machine.**

---

## 23. API Design

### OpenAI-Compatible Model API (Internal)

SAGE's model client speaks the OpenAI chat completion format. Both vLLM and llama.cpp server natively expose this API.

```
POST http://localhost:8001/v1/chat/completions
{
  "model": "qwen3-8b",
  "messages": [...],
  "tools": [...],     // Tool definitions
  "stream": true
}
```

### SAGE REST API

```yaml
openapi: 3.0.0
paths:
  /api/chat/sessions:
    post:
      summary: Create new chat session
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                profile: { type: string, enum: [general, analyst, coder, inspector] }
  
  /api/chat/sessions/{sessionId}/messages:
    post:
      summary: Send message to agent
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                message: { type: string }
                attachments: { type: array, items: { type: file } }
  
  /api/documents/{docId}:
    get:
      summary: Download generated document
  
  /api/admin/knowledge/ingest:
    post:
      summary: Ingest documents into knowledge base
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                files: { type: array, items: { type: file } }
                collection: { type: string }
  
  /api/admin/network-log:
    get:
      summary: Get network activity log
      parameters:
        - name: since
          in: query
          schema: { type: string, format: date-time }
  
  /api/admin/sovereignty-report:
    get:
      summary: Generate sovereignty verification report
```

---

## 24. Folder / Repository Structure

```
SAGE/
├── README.md
├── docker-compose.yml           # Single-command deployment
├── docker-compose.dev.yml       # Development overrides
├── Dockerfile.backend           # Python backend
├── Dockerfile.frontend          # Next.js frontend
├── Dockerfile.sandbox           # Code execution sandbox image
├── Makefile                     # Common commands
│
├── backend/                     # Python backend (FastAPI)
│   ├── pyproject.toml
│   ├── sage/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Configuration (env vars, YAML)
│   │   │
│   │   ├── api/                 # API routes
│   │   │   ├── chat.py
│   │   │   ├── tasks.py
│   │   │   ├── documents.py
│   │   │   ├── admin.py
│   │   │   └── auth.py
│   │   │
│   │   ├── agent/               # Agent orchestration
│   │   │   ├── engine.py        # Main ReAct loop
│   │   │   ├── planner.py       # Task planning
│   │   │   ├── executor.py      # Step executor
│   │   │   ├── router.py        # Model routing
│   │   │   ├── state.py         # Execution state machine
│   │   │   └── profiles/        # Agent profiles
│   │   │       ├── general.py
│   │   │       ├── analyst.py
│   │   │       ├── coder.py
│   │   │       └── inspector.py
│   │   │
│   │   ├── models/              # Model management
│   │   │   ├── registry.py      # Model registry
│   │   │   ├── client.py        # Model server client abstraction (OpenAI-compatible)
│   │   │   └── health.py        # Model health checks
│   │   │
│   │   ├── tools/               # Tool implementations
│   │   │   ├── base.py          # Tool base class + registry
│   │   │   ├── file_ops.py
│   │   │   ├── code_executor.py
│   │   │   ├── rag_search.py
│   │   │   ├── ocr.py
│   │   │   ├── vision.py
│   │   │   ├── doc_generator.py
│   │   │   ├── spreadsheet.py
│   │   │   └── calculator.py
│   │   │
│   │   ├── rag/                 # RAG pipeline
│   │   │   ├── ingestion.py
│   │   │   ├── chunker.py
│   │   │   ├── embedder.py
│   │   │   └── retriever.py
│   │   │
│   │   ├── docgen/              # Document generation
│   │   │   ├── word.py
│   │   │   ├── pptx.py
│   │   │   ├── xlsx.py
│   │   │   └── templates/       # .docx/.pptx templates
│   │   │
│   │   ├── multimodal/          # OCR & vision
│   │   │   ├── ocr_engine.py
│   │   │   └── vision_processor.py
│   │   │
│   │   ├── sandbox/             # Code execution
│   │   │   ├── manager.py
│   │   │   └── security.py
│   │   │
│   │   ├── auth/                # Authentication
│   │   │   ├── service.py
│   │   │   └── middleware.py
│   │   │
│   │   ├── audit/               # Audit logging
│   │   │   ├── logger.py
│   │   │   └── network_monitor.py
│   │   │
│   │   ├── db/                  # Database
│   │   │   ├── models.py        # SQLAlchemy models
│   │   │   └── migrations/      # Alembic migrations
│   │   │
│   │   └── core/                # Shared utilities
│   │       ├── schemas.py       # Pydantic schemas
│   │       ├── exceptions.py
│   │       └── utils.py
│   │
│   └── tests/
│       ├── test_agent/
│       ├── test_tools/
│       ├── test_rag/
│       └── test_api/
│
├── frontend/                    # Next.js frontend
│   ├── package.json
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── chat/
│   │   ├── documents/
│   │   ├── knowledge/
│   │   └── admin/
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── AgentSteps.tsx
│   │   ├── ToolCallCard.tsx
│   │   ├── NetworkMonitor.tsx
│   │   └── DocumentPreview.tsx
│   └── lib/
│       ├── api.ts
│       └── websocket.ts
│
├── config/                      # Configuration
│   ├── model_registry.yaml      # Model definitions
│   ├── tool_registry.yaml       # Tool configuration
│   └── sage.yaml                # Main config
│
├── scripts/                     # Utility scripts
│   ├── setup.sh                 # First-time setup
│   ├── airgap-bundle.sh         # Create air-gap deployment bundle
│   ├── verify-sovereignty.sh    # Network verification
│   └── seed-models.sh           # Download/verify models
│
├── templates/                   # Document templates
│   ├── approval_note.docx
│   ├── inspection_report.docx
│   └── presentation.pptx
│
└── docs/                        # Documentation
    ├── architecture.md
    ├── deployment.md
    ├── adding-models.md
    └── adding-tools.md
```

---

## 25. Development Phases

### Phase 0: Foundation (Week 1-2)
**Goal:** Skeleton that compiles, model server running, basic chat working.

- [ ] Project scaffolding (repo structure, Docker Compose)
- [ ] FastAPI backend with health check endpoints
- [ ] llama.cpp server setup with one model (Qwen3-8B Q4_K_M GGUF)
- [ ] Basic model client abstraction
- [ ] Simple chat endpoint (no agent loop — direct LLM call)
- [ ] Next.js frontend scaffold with basic chat UI
- [ ] Python CLI scaffold (Typer + Rich)
- [ ] WebSocket streaming (token-by-token)
- [ ] PostgreSQL setup with initial schema
- [ ] Basic JWT auth

### Phase 1: Agent Core (Week 3-4)
**Goal:** Working ReAct agent loop with basic tools.

- [ ] Agent engine (plan → act → observe → reflect loop)
- [ ] Tool base class and registry
- [ ] File I/O tools (read_file, write_file, list_dir)
- [ ] Model router (keyword heuristic + file-type detection)
- [ ] Agent step visualization in UI
- [ ] Structured audit logging
- [ ] Configuration system (YAML-based)

### Phase 2: Multimodal + RAG (Week 5-6)
**Goal:** OCR, vision model, RAG pipeline working end-to-end.

- [ ] OCR engine (Tesseract + PaddleOCR)
- [ ] Vision model integration (Qwen2.5-VL-7B)
- [ ] RAG ingestion pipeline (parse → chunk → embed → store)
- [ ] pgvector setup and hybrid retrieval
- [ ] Embedding model (BGE-M3 or nomic-embed-text)
- [ ] RAG search tool
- [ ] Knowledge base management UI
- [ ] Multi-model serving (reasoning + vision concurrently)

### Phase 3: Document Generation + Coding Agent (Week 7-8)
**Goal:** Deliverables pipeline and coding workflow complete.

- [ ] Word document generation (docx-template)
- [ ] PowerPoint generation
- [ ] Excel generation
- [ ] Document templates (approval note, inspection report)
- [ ] Code execution sandbox (Docker-based or subprocess)
- [ ] Coding agent profile (write → execute → verify → deliver)
- [ ] Document download and preview in UI
- [ ] Calculator tool

### Phase 4: Sovereignty + Polish (Week 9-10)
**Goal:** Network monitoring, audit UI, sovereignty proof, SIH demo readiness.

- [ ] Network monitor daemon (tcpdump-based)
- [ ] Network activity dashboard in UI
- [ ] Air-gap mode configuration
- [ ] `sage-admin verify-airgap` command
- [ ] Sovereignty verification report generation
- [ ] Audit log viewer in UI
- [ ] Agent profiles (analyst, coder, inspector)
- [ ] End-to-end demo workflows
- [ ] Performance optimization
- [ ] Error handling and fallback mechanisms
- [ ] Documentation

---

## 26. MVP vs Advanced Features

### MVP (SIH Demo Ready)

| Feature | Status |
|---------|--------|
| Chat with local LLM (streaming) | MVP |
| Agent loop (plan/act/observe) | MVP |
| Model routing (2+ task types) | MVP |
| OCR (Tesseract) | MVP |
| Vision model (Qwen2.5-VL) | MVP |
| RAG (basic: ingest + search) | MVP |
| Word document generation | MVP |
| Code execution (subprocess sandbox) | MVP |
| Audit logging | MVP |
| Network activity display | MVP |
| Basic auth (JWT) | MVP |
| Agent transparency UI | MVP |

### Advanced (Post-SIH)

| Feature | Phase |
|---------|-------|
| vLLM migration for production scale | Post-MVP |
| Docker sandbox for code execution | Post-MVP |
| LDAP/AD integration | Post-MVP |
| Fine-tuned task classifier for routing | Post-MVP |
| Streaming document preview | Post-MVP |
| Multi-user concurrent sessions | Post-MVP |
| Model fine-tuning pipeline | Advanced |
| Multi-agent collaboration | Advanced |
| Workflow templates (predefined multi-step flows) | Advanced |
| Custom tool development SDK | Advanced |
| Kubernetes deployment | Advanced |
| HA / failover | Advanced |

---

## 27. SIH Demo Strategy

### Demo Structure (15-20 minutes)

> [!IMPORTANT]
> The demo should be scripted, rehearsed, and run on pre-warmed models. Cold model loading takes 10-30 seconds and kills demo flow.

#### Opening (2 min)
- Show the SAGE dashboard. Explain the architecture briefly.
- Show the Network Monitor — "Notice: zero external connections."

#### Demo A: Model Routing (3 min)
1. Type a **document analysis** query → UI shows "Routing to: Qwen3-8B (Reasoning)"
2. Type a **coding** query → UI shows "Routing to: Qwen3-Coder-8B (Coding)"
3. Upload an **image** → UI shows "Routing to: Qwen2.5-VL-7B (Vision)"
4. **Highlight:** "The system automatically selects the right model. No user intervention needed."

#### Demo B: Inspection Workflow (5 min)
1. Upload a scanned inspection report (prepared beforehand).
2. Show the Agent Steps panel: "Planning... Step 1: OCR... Step 2: Search SOPs... Step 3: Analyze..."
3. Agent runs OCR → extracts findings → searches RAG → reasons → generates approval note.
4. Download the generated Word document. Open it. Show it's a professional, structured document.
5. **Highlight:** "End-to-end automation. From a scanned PDF to an approval note. No external API. No data left this machine."

#### Demo C: Coding Workflow (3 min)
1. Ask: "Write a Python function to parse CSV data and calculate monthly averages."
2. Agent: Plans → writes code → executes in sandbox → tests → delivers working code file.
3. Show the output file and execution results.
4. **Highlight:** "The agent doesn't just generate code. It executes, tests, and verifies."

#### Demo D: Multimodal (3 min)
1. Upload an engineering drawing or P&ID diagram.
2. Vision model describes the diagram.
3. Agent extracts structured information (components, connections, labels).
4. **Highlight:** "This handles real industrial documents — drawings, handwritten notes, P&IDs."

#### Demo E: Sovereignty Proof (3 min)
1. Open the Network Monitor → show zero external connections.
2. Run `sage-admin verify-airgap` → show the sovereignty report.
3. Open the Audit Log → show every model call, tool execution, file operation.
4. **Highlight:** "Every byte is accounted for. Every action is logged. Nothing left this machine."

### Pre-Demo Preparation

```
1. Pre-warm all models (run a dummy prompt to each)
2. Pre-ingest sample SOPs into RAG knowledge base
3. Pre-download all dependencies (verify offline operation)
4. Prepare sample inputs:
   - Scanned inspection report (PDF)
   - Engineering drawing (PNG/PDF)
   - Coding task (text prompt)
5. Run full demo 3 times to ensure reliability
6. Have fallback screenshots/recordings if live demo fails
```

---

> **Cross-References:**
> - Architecture & Foundation → `01_Architecture_And_Foundation.md`
> - Model Serving & Routing → `02_Model_Serving_And_Agent_Orchestration.md`
> - Tool/Plugin & RAG details → `03_Tools_RAG_And_Multimodal.md`
> - Backend, Frontend & Security → `04_Backend_Frontend_And_Security.md`
> - Hardware, Testing & Deployment → `06_Hardware_Testing_And_Deployment.md`
