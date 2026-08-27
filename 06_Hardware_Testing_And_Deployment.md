# SAGE — Section 6: Hardware, Testing, Deployment & Risks

**SIH Problem Statement:** SIH26117 — Sovereign On-Premise Agentic AI Workbench  
**Sponsoring Organization:** Mangalore Refinery and Petrochemicals Limited (MRPL)  
**Date:** 2026-08-26

---

## 28. Hardware Requirements

### SIH Demo (Minimum)

| Component | Specification | Notes |
|-----------|--------------|-------|
| **GPU** | NVIDIA RTX 3060 12GB or RTX 4060 Ti 16GB | Runs 1 quantized model at a time |
| **RAM** | 32 GB DDR4 | Backend + DB + model loading overhead |
| **CPU** | Intel i7/Ryzen 7 (8+ cores) | OCR is CPU-intensive |
| **Storage** | 256 GB SSD | ~30GB for models, ~10GB for system, rest for documents |
| **OS** | Ubuntu 22.04 LTS or Windows 11 + WSL2 | Linux preferred for Docker/networking |

### Comfortable Demo (Recommended)

| Component | Specification | Notes |
|-----------|--------------|-------|
| **GPU** | NVIDIA RTX 4070 Ti 12GB or RTX 4090 24GB | Can keep 2 models loaded simultaneously |
| **RAM** | 64 GB DDR5 | Comfortable headroom |
| **CPU** | Intel i9/Ryzen 9 (12+ cores) | Fast OCR + document processing |
| **Storage** | 512 GB NVMe SSD | Room for multiple model variants |

### Production (Target)

| Component | Specification | Notes |
|-----------|--------------|-------|
| **GPU** | 2× NVIDIA A6000 48GB or 1× A100 80GB | Multiple models loaded concurrently |
| **RAM** | 128 GB ECC DDR5 | |
| **CPU** | AMD EPYC or Intel Xeon (32+ cores) | |
| **Storage** | 2 TB NVMe + 10 TB HDD | Models + document archive |

---

## 29. Model Recommendations

### Model Selection Matrix (SIH Demo — 16-24GB VRAM)

| Task | Model | Size (Q4) | VRAM | Why |
|------|-------|-----------|------|-----|
| **Reasoning / General** | Qwen3-8B-Instruct | ~5 GB | ~6 GB | Best overall quality for size; strong reasoning and tool-calling |
| **Coding** | Qwen3-Coder-8B | ~5 GB | ~6 GB | Purpose-built for code; excellent agentic coding performance |
| **Vision / OCR** | Qwen2.5-VL-7B-Instruct | ~5 GB | ~6 GB | Strong vision understanding; handles documents, diagrams, handwriting |
| **Embedding** | nomic-embed-text (137M) | ~270 MB | <1 GB | Fast, local, good quality for RAG; served via sentence-transformers |

**Total VRAM (worst case, all loaded):** ~19 GB — fits on a 24GB GPU.

**On 12-16GB VRAM:** Swap models between tasks. Keep reasoning model hot-loaded. Vision and coding models loaded on-demand (~10s swap time).

### Alternative Models

| Task | Alternative | Trade-off |
|------|-------------|-----------|
| Reasoning | Phi-4-mini (3.8B) | Smaller but less capable; good for very constrained hardware |
| Reasoning | Gemma-4-12B | Excellent quality but needs more VRAM |
| Coding | DeepSeek-Coder-V2-Lite (16B) | Better quality but larger |
| Vision | Phi-4-Multimodal (5.6B) | Smaller, good for charts/docs |
| Embedding | BGE-M3 | Better quality (dense+sparse) but heavier |

---

## 30. How Models Can Be Added Later

### Step 1: Add to Registry

```yaml
# config/model_registry.yaml
models:
  - id: gemma-4-12b
    name: "Gemma 4 12B"
    model_path: "/opt/sage/models/gemma-4-12b-Q4_K_M.gguf"
    server_port: 8004
    capabilities: ["reasoning", "analysis"]
    priority: 2                    # Lower = preferred
    min_vram_gb: 8
    context_length: 32768
    
  - id: deepseek-coder-v2
    name: "DeepSeek Coder V2"
    model_path: "/opt/sage/models/deepseek-coder-v2-16b-Q4_K_M.gguf"
    server_port: 8005
    capabilities: ["coding"]
    priority: 1
    min_vram_gb: 10
    context_length: 65536
```

### Step 2: Download the Model

```bash
# Download GGUF from HuggingFace (on internet-connected machine)
huggingface-cli download bartowski/gemma-4-12b-GGUF --include "*Q4_K_M*" --local-dir /opt/sage/models/
```

### Step 3: Restart SAGE

The model registry auto-discovers new models at startup. No code changes needed. The router automatically routes to the new model based on its declared capabilities and priority.

### Design Principles for Model Extensibility

1. **Models are data, not code.** Adding a model is a YAML config change, not a code change.
2. **Capabilities are tags.** `["reasoning", "coding"]` — the router matches task requirements to model capabilities.
3. **Priority ordering.** Multiple models can share capabilities; the router picks the highest-priority available model.
4. **Health-checked.** Models that fail health checks are automatically excluded from routing.

---

## 31. Testing Strategy

### Testing Layers

| Layer | Type | Tool | Coverage Target |
|-------|------|------|----------------|
| **Unit** | Individual functions | pytest | Tools, router, chunker, parsers |
| **Integration** | Component interactions | pytest + test model server | Agent loop, RAG pipeline, doc gen |
| **E2E** | Full workflow | pytest + Playwright | Complete demo workflows |
| **Sovereignty** | Network verification | tcpdump + assertion script | Zero external connections |
| **Performance** | Latency benchmarks | Custom + time measurement | Response time targets |

### Critical Test Cases

```python
# test_sovereignty.py
def test_no_external_connections():
    """Verify zero bytes sent to external IPs during a full workflow."""
    with network_capture() as capture:
        run_full_inspection_workflow()
    external_packets = [p for p in capture if not is_localhost(p.dest)]
    assert len(external_packets) == 0

# test_model_routing.py
def test_routes_vision_for_image_input():
    task = Task(prompt="Analyze this", attachments=[ImageFile("test.png")])
    model = router.route(task)
    assert "vision" in model.capabilities

def test_routes_coding_for_code_request():
    task = Task(prompt="Write a Python function to sort a list")
    model = router.route(task)
    assert "coding" in model.capabilities

# test_agent_loop.py
def test_agent_completes_within_max_steps():
    result = agent.execute("Calculate 2+2")
    assert result.state == AgentState.COMPLETED
    assert result.total_steps <= agent.max_steps

def test_agent_handles_tool_error():
    # Mock a tool that raises an error
    result = agent.execute("Read file /nonexistent/path")
    assert result.state == AgentState.COMPLETED  # Agent should recover
```

---

## 32. Failure Handling & Fallback Mechanisms

| Failure | Detection | Fallback |
|---------|-----------|----------|
| **Model unavailable** | Health check fails | Route to next model with same capability; if none → error with clear message |
| **Model returns garbage** | Output validation (no valid JSON for tool calls) | Retry up to 3 times with modified prompt; if still failing → return partial result |
| **Tool execution error** | Exception caught | Log error, return error description to agent, let agent re-plan |
| **Sandbox timeout** | 30s timer | Kill container, return timeout error to agent |
| **RAG returns no results** | Empty result set | Agent proceeds without RAG context; notes "no relevant documents found" |
| **OCR extraction fails** | Empty or garbled text | Fall back to vision model for direct interpretation |
| **Document generation fails** | Template error | Return error with details; agent can retry with corrected data |
| **Infinite agent loop** | Step counter > max_steps | Force termination, return partial results |
| **VRAM exhaustion** | CUDA OOM error | Unload unused models, retry with smaller batch; if persists → error |
| **Database connection lost** | Connection error | Retry with exponential backoff; queue audit logs in memory |

### Circuit Breaker Pattern

```python
class ModelCircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds
    
    def call(self, model_id: str, request):
        if self.is_open(model_id):
            raise ModelUnavailableError(f"{model_id} circuit breaker open")
        try:
            result = self.model_client.call(request)
            self.record_success(model_id)
            return result
        except Exception as e:
            self.record_failure(model_id)
            raise
```

---

## 33. Performance Considerations

### Latency Targets

| Operation | Target | Acceptable |
|-----------|--------|-----------|
| First token (reasoning) | <2s | <5s |
| First token (coding) | <2s | <5s |
| First token (vision) | <3s | <8s |
| OCR (single page) | <3s | <10s |
| RAG search | <500ms | <2s |
| Document generation | <5s | <15s |
| Model routing | <50ms | <200ms |
| Complete inspection workflow | <60s | <120s |

### Optimization Strategies

1. **Model pre-loading:** Keep primary model in VRAM at all times. Pre-warm on startup.
2. **Embedding caching:** Cache frequently-queried embeddings in Redis.
3. **Async everything:** FastAPI's async + asyncio for all I/O operations.
4. **Streaming responses:** Don't wait for full generation; stream tokens as they come.
5. **Lazy tool loading:** Only import heavy tool dependencies when the tool is first used.
6. **Document template caching:** Parse templates once, cache the parsed object.
7. **Connection pooling:** PostgreSQL connection pool (asyncpg with pool size=20).
8. **KV cache optimization:** Configure llama.cpp server's `--cache-reuse` / vLLM's prefix caching to retain KV cache between requests.

---

## 34. Deployment Strategy

### Development

```bash
# Start all services
docker compose -f docker-compose.dev.yml up

# Backend hot-reload
cd backend && uvicorn sage.main:app --reload

# Frontend hot-reload
cd frontend && npm run dev
```

### Production (Single Machine)

```bash
# Build images
docker compose build

# Start
docker compose up -d

# Verify
docker compose ps
sage-admin health-check
sage-admin verify-airgap
```

### Docker Compose Architecture

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [postgres, redis, model-server]
    environment:
      - DATABASE_URL=postgresql://sage:sage@postgres:5432/sage
      - REDIS_URL=redis://redis:6379
      - MODEL_SERVER_URL=http://model-server:8001
      - AIRGAP_MODE=true
    volumes:
      - ./workspace:/workspace
      - ./templates:/templates

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [backend]

  postgres:
    image: pgvector/pgvector:pg16
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      - POSTGRES_DB=sage
      - POSTGRES_USER=sage
      - POSTGRES_PASSWORD=sage

  redis:
    image: redis:7-alpine
    volumes: [redisdata:/data]

  # For production, replace with vLLM:
  #   image: vllm/vllm-openai:latest
  #   command: --model /models/qwen3-8b --served-model-name qwen3-8b
  model-server:
    image: ghcr.io/ggerganov/llama.cpp:server
    ports: ["8001:8001"]
    command: >
      --model /models/qwen3-8b-Q4_K_M.gguf
      --port 8001
      --host 0.0.0.0
      --ctx-size 8192
      --n-gpu-layers 99
    volumes:
      - ./models:/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

volumes:
  pgdata:
  redisdata:
```

---

## 35. Sovereignty Proof

### Three Layers of Proof

#### Layer 1: Network Monitoring (Continuous)

```python
# audit/network_monitor.py
class NetworkMonitor:
    """Continuously monitors all network connections and logs them."""
    
    def start(self):
        # Uses psutil to monitor all connections
        for conn in psutil.net_connections():
            if not self.is_local(conn.raddr):
                self.alert(f"EXTERNAL CONNECTION DETECTED: {conn}")
                self.log(conn, severity="CRITICAL")
            else:
                self.log(conn, severity="INFO")
    
    def is_local(self, addr):
        return addr is None or addr.ip in ("127.0.0.1", "::1", "0.0.0.0")
```

#### Layer 2: Firewall Rules (Preventive)

```bash
# scripts/setup-firewall.sh
# Block ALL outbound traffic except localhost
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT    # Internal network
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT  # Docker network
iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT # LAN
iptables -A OUTPUT -j LOG --log-prefix "SAGE-BLOCKED: "
iptables -A OUTPUT -j DROP
```

#### Layer 3: Verification Report (On-Demand)

```
========================================
SAGE SOVEREIGNTY VERIFICATION REPORT
========================================
Date: 2026-08-26 15:01:33 IST
Duration: 60 seconds
Mode: AIR-GAP VERIFICATION

NETWORK ANALYSIS:
  Total packets captured: 1,247
  Internal packets: 1,247
  External packets: 0 ✅
  Blocked connections: 0

MODEL VERIFICATION:
  qwen3:8b ............... LOCAL ✅ (sha256: abc123...)
  qwen3-coder:8b ......... LOCAL ✅ (sha256: def456...)
  qwen2.5-vl:7b ......... LOCAL ✅ (sha256: ghi789...)
  nomic-embed-text ....... LOCAL ✅ (sha256: jkl012...)

SERVICE VERIFICATION:
  Model Server ........... localhost:8001 ✅
  PostgreSQL ............. localhost:5432 ✅
  Redis .................. localhost:6379 ✅
  Backend ................ localhost:8000 ✅
  Frontend ............... localhost:3000 ✅

DNS VERIFICATION:
  DNS queries made: 0 ✅

VERDICT: ✅ SOVEREIGN — No external data transmission detected.
========================================
```

---

## 36. Architectural Mistakes to Avoid

> [!WARNING]
> These are common pitfalls that kill SIH projects and real-world sovereign AI deployments.

| # | Mistake | Why It's Deadly | What To Do Instead |
|---|---------|----------------|-------------------|
| 1 | **Using LangChain for everything** | Massive dependency tree, telemetry phone-home, slow, abstracts away understanding | Build a lightweight custom agent loop (~500 lines). You'll understand every line. |
| 2 | **Treating RAG as "just embed and search"** | Industrial documents have structure (tables, cross-refs). Naive chunking destroys it. | Invest in structured document parsing. Use layout-aware chunkers. |
| 3 | **Single model assumption** | "We'll use Llama 3 for everything" → fails at vision, fails at code, stuck when better models emerge. | Model registry + router from day one. Abstract the model behind an interface. |
| 4 | **Ignoring model cold-load time** | Judges tap their feet for 30 seconds during demo. | Pre-warm all models before demo. Start model server processes at boot. |
| 5 | **Building a chatbot and calling it an agent** | Judges and MRPL reviewers will see through this immediately. | Show multi-step execution, tool calls, error recovery, and deliverable output. |
| 6 | **Over-engineering for production** | Kubernetes, Istio, Kafka — for a 3-person team's SIH submission. | Docker Compose. One machine. Modular monolith. Scale later. |
| 7 | **Ignoring the "proof" requirement** | Claiming "it's local" without evidence. | Network monitor, audit logs, and sovereignty report are **mandatory** demo components. |
| 8 | **Not handling LLM failures gracefully** | Model returns malformed JSON → entire workflow crashes → demo fails. | Validate every LLM output. Retry with modified prompts. Fallback to simpler approaches. |
| 9 | **Hardcoding prompts** | Different models need different prompt formats. | Prompt templates per model family in config, not in code. |
| 10 | **Embedding external CLI agents as runtime dependencies** | Fragile integration, loss of control, conflicting model management. | Build native coding agent within SAGE's agent engine. |
| 11 | **Using ChromaDB in production** | No ACID, no relational queries, another process to manage. | pgvector — one DB for everything. |
| 12 | **Skipping structured output validation** | Agent generates a document with missing fields → broken Word file. | Pydantic validation between LLM output and document generation. Always. |

---

## 37. Architecture Diagrams

### A. High-Level Architecture Diagram

```
┌─────────────────────────────── SAGE SYSTEM ────────────────────────────────┐
│                                                                             │
│   ┌─────────────┐         ┌──────────────────────────────────────────┐     │
│   │             │  HTTPS  │              SAGE BACKEND                │     │
│   │   Web UI    │◄───────►│                                          │     │
│   │  (Next.js)  │   WS    │   ┌──────────┐    ┌─────────────────┐   │     │
│   │             │         │   │ API Layer │───►│  Agent Engine    │   │     │
│   └─────────────┘         │   └──────────┘    │  ┌───────────┐  │   │     │
│                            │                   │  │  Planner  │  │   │     │
│                            │                   │  │  Executor │  │   │     │
│                            │                   │  │  Reflector│  │   │     │
│                            │                   │  └───────────┘  │   │     │
│                            │                   └────────┬────────┘   │     │
│                            │                            │            │     │
│                            │              ┌─────────────┼─────────┐  │     │
│                            │              │             │         │  │     │
│                            │         ┌────▼────┐  ┌─────▼────┐ ┌─▼──▼─┐  │
│                            │         │  Model  │  │   Tool   │ │ Doc  │  │
│                            │         │  Router │  │ Registry │ │ Gen  │  │
│                            │         └────┬────┘  └────┬─────┘ └──┬──┘  │
│                            │              │            │          │     │
│                            └──────────────┼────────────┼──────────┼─────┘
│                                           │            │          │
│   ┌───────────────────────────────────────┼────────────┼──────────┼─────┐
│   │            INFERENCE LAYER            │            │          │     │
│   │   ┌──────────────┐ ┌──────────────┐  │            │          │     │
│   │   │  llama.cpp /  │ │  llama.cpp / │  │            │          │     │
│   │   │  vLLM         │ │  vLLM        │◄─┘            │          │     │
│   │   │  (Reasoning)  │ │  (Vision)    │               │          │     │
│   │   └──────────────┘ └──────────────┘               │          │     │
│   └────────────────────────────────────────────────────┘          │     │
│                                                                    │     │
│   ┌───────────────────────────────────────────────────────────────┐│     │
│   │            DATA LAYER                                         ││     │
│   │   ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ ││     │
│   │   │ PostgreSQL   │ │  Redis   │ │  File    │ │  Sandbox   │ ││     │
│   │   │ + pgvector   │ │  Cache   │ │  System  │ │  (Docker)  │◄┘│     │
│   │   └──────────────┘ └──────────┘ └──────────┘ └────────────┘  │     │
│   └───────────────────────────────────────────────────────────────┘     │
│                                                                         │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │   SECURITY LAYER:  Firewall │ Network Monitor │ Audit Logger  │     │
│   └───────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

### B. Detailed Component Interaction Diagram

```mermaid
sequenceDiagram
    participant U as User (Browser)
    participant API as SAGE API
    participant AE as Agent Engine
    participant MR as Model Router
    participant MS as Model Server
    participant TR as Tool Registry
    participant RAG as RAG Engine
    participant DG as Doc Generator
    participant AU as Audit Logger

    U->>API: POST /chat/message (+ file upload)
    API->>AU: Log: user_request
    API->>AE: Execute task
    
    AE->>MR: Route task
    MR-->>AE: Selected model: vision (has image)
    AE->>AU: Log: model_selected
    
    Note over AE: PLAN phase
    AE->>MS: Generate plan (reasoning model)
    MS-->>AE: Plan: [OCR, RAG search, analyze, generate doc]
    
    Note over AE: ACT phase (Step 1: OCR)
    AE->>TR: Execute: ocr_extract(file)
    TR-->>AE: OCR text result
    AE->>AU: Log: tool_call(ocr)
    
    Note over AE: ACT phase (Step 2: RAG)
    AE->>TR: Execute: rag_search(query)
    TR->>RAG: Hybrid search
    RAG-->>TR: Top-5 chunks with sources
    TR-->>AE: Search results
    AE->>AU: Log: tool_call(rag)
    
    Note over AE: ACT phase (Step 3: Analyze)
    AE->>MS: Generate analysis (reasoning model)
    MS-->>AE: Structured findings
    AE->>AU: Log: model_inference
    
    Note over AE: ACT phase (Step 4: Generate Doc)
    AE->>TR: Execute: generate_word(data)
    TR->>DG: Render template
    DG-->>TR: Word file path
    TR-->>AE: Document ready
    AE->>AU: Log: tool_call(doc_gen)
    
    AE-->>API: Task complete + file path
    API-->>U: Stream result + download link
```

### C. End-to-End Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        DATA FLOW — ALL LOCAL                              │
│                                                                           │
│  INPUT                    PROCESSING                      OUTPUT          │
│  ─────                    ──────────                      ──────          │
│                                                                           │
│  ┌──────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────┐    │
│  │ User     │───►│ API Gateway │───►│ Agent Engine │───►│ Word Doc │    │
│  │ Upload   │    │ (validate,  │    │ (plan, act,  │    │ PPTX     │    │
│  │ (PDF,    │    │  auth,      │    │  observe,    │    │ XLSX     │    │
│  │  image,  │    │  log)       │    │  reflect)    │    │ Code     │    │
│  │  text)   │    └──────┬──────┘    └──────┬───────┘    │ Report   │    │
│  └──────────┘           │                  │            └──────────┘    │
│                          │                  │                            │
│                          ▼                  ▼                            │
│              ┌──────────────────────────────────────────┐               │
│              │           LOCAL SERVICES ONLY             │               │
│              │                                           │               │
│              │  Model Server ─ localhost:8001            │               │
│              │  PostgreSQL ─ localhost:5432              │               │
│              │  Redis ───── localhost:6379               │               │
│              │  Tesseract ── local process               │               │
│              │  Docker ──── unix socket                  │               │
│              │                                           │               │
│              │  ❌ NO EXTERNAL CONNECTIONS               │               │
│              └──────────────────────────────────────────┘               │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  AUDIT TRAIL: Every arrow above is logged with timestamp,       │    │
│  │  user_id, operation, input hash, output hash, latency.          │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 38. Risks & Mitigations

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|------------|
| 1 | **Models too large for demo GPU** | Medium | CRITICAL | Use Q4_K_M quantization. Test on target hardware early. Have fallback to smaller models (Phi-4-mini). |
| 2 | **Model quality insufficient for agentic tool-calling** | Medium | HIGH | Test tool-calling extensively with chosen models. Qwen3 has strong tool-calling support. Use structured output enforcement. |
| 3 | **OCR quality poor on real industrial documents** | Medium | HIGH | Use PaddleOCR for complex layouts. Supplement with vision LLM. Pre-process images (deskew, denoise). |
| 4 | **RAG retrieval returns irrelevant results** | Medium | MEDIUM | Hybrid search (vector + BM25). Structured chunking with metadata. Manual evaluation of retrieval quality. |
| 5 | **Demo fails live** | Low | CRITICAL | Have pre-recorded backup. Pre-warm all models. Run demo 10+ times in rehearsal. |
| 6 | **Agent gets stuck in infinite loop** | Medium | MEDIUM | Hard step limit (15). Timeout per step (60s). Circuit breaker on model failures. |
| 7 | **Judges question sovereignty claim** | Low | HIGH | Three-layer proof: network monitor + firewall + verification report. Show tcpdump output live. |
| 8 | **Team burns out on scope** | High | HIGH | Strict MVP scope. Build foundation first. Add features incrementally. Resist feature creep. |
| 9 | **Docker/GPU issues on demo machine** | Medium | HIGH | Test on the exact demo hardware. Have a backup machine. Pre-build all Docker images. |
| 10 | **Model hallucinations in generated documents** | High | MEDIUM | Always include source attributions. Pydantic validation. Human-in-the-loop for production (not demo). |

---

## Summary: Build vs Integrate vs Avoid

| Component | Build | Integrate | Avoid |
|-----------|-------|-----------|-------|
| Agent orchestration loop | ✅ Custom | | LangChain/LangGraph (too heavy) |
| Model serving | | ✅ vLLM / llama.cpp server | Rolling your own inference |
| Model routing | ✅ Custom classifier | | LLM-based routing |
| Tool framework | ✅ Custom (simple) | | Heavy plugin frameworks |
| RAG pipeline | ✅ Custom ingestion/retrieval | ✅ pgvector, sentence-transformers | Managed RAG services |
| OCR | | ✅ Tesseract + PaddleOCR | Cloud OCR APIs |
| Vision understanding | | ✅ Qwen2.5-VL via model server | External vision APIs |
| Document generation | | ✅ python-docx-template, python-pptx, openpyxl | LibreOffice server (complex) |
| Code sandbox | | ✅ Docker | Unsandboxed `exec()` |
| Authentication | ✅ Simple JWT | | Keycloak (overkill for MVP) |
| Frontend | ✅ Custom Next.js | | Generic chat UI libraries |
| Database | | ✅ PostgreSQL + pgvector | MongoDB, multiple DBs |
| Coding agent | ✅ Custom agent profile | | External CLI tools as runtime dependency |
| Network monitoring | ✅ Custom (psutil + tcpdump) | | Expensive SIEM tools |

---

## Proposed Changes

### Phase 1 (Foundation + Agent Core)

#### [NEW] `docker-compose.yml` — Single-command deployment
#### [NEW] `backend/sage/main.py` — FastAPI entry point
#### [NEW] `backend/sage/agent/engine.py` — ReAct agent loop
#### [NEW] `backend/sage/agent/router.py` — Model routing logic
#### [NEW] `backend/sage/models/client.py` — Model server client abstraction (OpenAI-compatible)
#### [NEW] `backend/sage/models/registry.py` — Model registry
#### [NEW] `backend/sage/tools/base.py` — Tool base class + registry
#### [NEW] `backend/sage/tools/file_ops.py` — File I/O tools
#### [NEW] `backend/sage/api/chat.py` — Chat API + WebSocket
#### [NEW] `backend/sage/auth/service.py` — JWT auth
#### [NEW] `backend/sage/audit/logger.py` — Structured audit logger
#### [NEW] `backend/sage/config.py` — Configuration management
#### [NEW] `config/model_registry.yaml` — Model definitions
#### [NEW] `frontend/app/` — Next.js application scaffold
#### [NEW] `frontend/components/ChatWindow.tsx` — Main chat interface

### Phase 2 (RAG + Multimodal)

#### [NEW] `backend/sage/rag/` — Full RAG pipeline
#### [NEW] `backend/sage/multimodal/` — OCR + vision processing
#### [NEW] `backend/sage/tools/rag_search.py` — RAG search tool
#### [NEW] `backend/sage/tools/ocr.py` — OCR tool
#### [NEW] `backend/sage/tools/vision.py` — Vision analysis tool

### Phase 3 (Doc Gen + Coding Agent)

#### [NEW] `backend/sage/docgen/` — Document generation pipeline
#### [NEW] `backend/sage/sandbox/` — Code execution sandbox
#### [NEW] `backend/sage/agent/profiles/` — Agent profiles
#### [NEW] `templates/` — Document templates (.docx, .pptx)

### Phase 4 (Sovereignty + Polish)

#### [NEW] `backend/sage/audit/network_monitor.py` — Network monitoring
#### [NEW] `scripts/verify-sovereignty.sh` — Verification script
#### [NEW] `scripts/airgap-bundle.sh` — Air-gap deployment bundler

---

## Verification Plan

### Automated Tests
- `pytest backend/tests/` — Unit and integration tests
- `pytest backend/tests/test_sovereignty.py` — Network verification tests
- `npm test` in frontend — Component tests

### Manual Verification
- Run full inspection workflow end-to-end
- Run coding workflow end-to-end
- Run `sage-admin verify-airgap` on target hardware
- Demo rehearsal (3+ complete run-throughs)
- Test on exact SIH demo hardware

---

> **Cross-References:**
> - Architecture & Foundation → `01_Architecture_And_Foundation.md`
> - Model Serving & Routing → `02_Model_Serving_And_Agent_Orchestration.md`
> - Tool/Plugin & RAG details → `03_Tools_RAG_And_Multimodal.md`
> - Backend, Frontend & Security → `04_Backend_Frontend_And_Security.md`
> - Development Phases & Demo → `05_Development_Phases_And_Demo_Strategy.md`
