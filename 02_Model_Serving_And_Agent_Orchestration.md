# SAGE — Section 2: Model Serving, Routing & Agent Orchestration

**SIH Problem Statement:** SIH26117 — Sovereign On-Premise Agentic AI Workbench  
**Sponsoring Organization:** Mangalore Refinery and Petrochemicals Limited (MRPL)  
**Date:** 2026-08-26

---

## 6. Model-Serving Architecture

### Architecture: Multi-Instance Model Servers

```
┌─────────────────────────────────────────┐
│            Model Registry               │
│  ┌─────────────────────────────────┐    │
│  │  model_id: qwen3-8b            │    │
│  │  server:   localhost:8001       │    │
│  │  type:     reasoning           │    │
│  │  vram:     ~6GB (Q4_K_M)       │    │
│  ├─────────────────────────────────┤    │
│  │  model_id: qwen3-coder-8b      │    │
│  │  server:   localhost:8002       │    │
│  │  type:     coding              │    │
│  ├─────────────────────────────────┤    │
│  │  model_id: qwen2.5-vl-7b       │    │
│  │  server:   localhost:8003       │    │
│  │  type:     vision              │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### Multi-Model Serving Strategy

For workflows that need both reasoning + vision (inspection workflow), we need both models ready simultaneously.

**Strategy:**
- **SIH Demo (single GPU, 16-24GB VRAM):** Run llama.cpp server instances. Keep the primary reasoning model hot-loaded; start vision/coding model servers on-demand (~5s startup with pre-loaded GGUF files).
- **Production (multi-GPU):** Use vLLM with multi-model serving, each model pinned to a GPU. Zero swap latency. Continuous batching for concurrent users.

### Model Lifecycle

```
1. SAGE boots → reads model_registry.yaml
2. For each model entry:
   a. Check if GGUF/safetensors model file exists at configured path
   b. If missing → error in air-gap mode; download in online mode
   c. Start model server process (llama-server or vLLM)
   d. Verify model health (send test prompt to /v1/chat/completions)
3. Mark models as READY / DEGRADED / UNAVAILABLE
4. Router only routes to READY models
```

---

## 7. Model-Routing Architecture

### Router Design

The model router is **not** an LLM. It is a **deterministic classifier** that examines the task and selects the appropriate model. Using an LLM to route to an LLM is circular, slow, and unreliable.

```python
# Simplified router logic
class ModelRouter:
    def route(self, task: Task) -> ModelConfig:
        # 1. Explicit task type (if set by agent profile)
        if task.required_capability:
            return self.registry.get_by_capability(task.required_capability)
        
        # 2. Input modality detection
        if task.has_images or task.has_scanned_pdf:
            return self.registry.get_by_capability("vision")
        
        # 3. Task classification (keyword + heuristic)
        task_type = self.classifier.classify(task.prompt)
        
        if task_type == "coding":
            return self.registry.get_by_capability("coding")
        elif task_type == "analysis":
            return self.registry.get_by_capability("reasoning")
        else:
            return self.registry.get_default()
```

### Classification Strategy

| Signal | Method | Example |
|--------|--------|---------|
| **File attachment type** | MIME type check | `.png` → vision, `.py` → coding |
| **Explicit task type** | Agent profile sets it | Coding agent always uses coding model |
| **Keyword heuristics** | Regex + keyword sets | "write code", "function", "debug" → coding |
| **Lightweight classifier** | Small fine-tuned model (optional) | TF-IDF + logistic regression on task prompts |
| **User override** | UI dropdown | User selects "use vision model" |

### Why Not Use an LLM to Route?

1. **Circular dependency** — You need a model running to choose which model to run.
2. **Latency** — Adds 2-5s to every request just for routing.
3. **Reliability** — Small models are unreliable at meta-reasoning about their own capabilities.
4. **Simplicity** — A 50-line classifier handles 95% of cases correctly.

> [!TIP]
> For the SIH demo, keyword heuristics + file-type detection is **more than sufficient** and far more impressive than a flaky LLM-based router.

---

## 8. Agent Orchestration Architecture

### Core Loop: Modified ReAct

```
                    ┌──────────────┐
                    │   User Task  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │    PLAN      │ ◄── Break task into steps
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
              ┌────►│    ACT       │ ◄── Select & call tool
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │   OBSERVE    │ ◄── Capture tool output
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │   REFLECT    │ ◄── Evaluate: done? retry? replan?
              │     └──────┬───────┘
              │            │
              │       ┌────┴────┐
              │       │         │
              │    ┌──▼──┐  ┌──▼──┐
              └────┤RETRY│  │DONE │
                   └─────┘  └──┬──┘
                               │
                        ┌──────▼───────┐
                        │   DELIVER    │ ◄── Generate output artifacts
                        └──────────────┘
```

### Agent Profiles

Rather than one monolithic agent, SAGE defines **profiles** — preconfigured agent personalities with specific tool sets and model preferences.

| Profile | Model Preference | Tools Available | Use Case |
|---------|-----------------|-----------------|----------|
| `analyst` | reasoning | RAG search, OCR, doc generator | Document analysis, report writing |
| `coder` | coding | File I/O, code executor, sandbox | Code generation, debugging |
| `inspector` | vision + reasoning | OCR, RAG, doc generator | Inspection report workflows |
| `general` | reasoning | All tools | Open-ended tasks |

### Execution State Machine

```python
class AgentState(Enum):
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    FAILED = "failed"

class AgentExecution:
    max_steps: int = 15          # Hard limit to prevent infinite loops
    max_retries_per_step: int = 3
    state: AgentState
    plan: list[Step]
    history: list[StepResult]    # Full execution trace for audit
    tools: list[Tool]
    model: ModelConfig
```

### Multi-Step Execution Example (Inspection Workflow)

```
Step 1: [PLAN]    "I need to: (1) OCR the scanned report, (2) extract findings,
                   (3) search SOPs, (4) reason over findings, (5) generate approval note"
Step 2: [ACT]     tool=ocr_extract, input=uploaded_scan.pdf
Step 3: [OBSERVE] OCR output: "Valve V-301 shows 2.1mm wall thinning..."
Step 4: [ACT]     tool=rag_search, query="V-301 wall thinning threshold SOP"
Step 5: [OBSERVE] Retrieved SOP-MR-114: "Min wall thickness for V-301: 3.5mm..."
Step 6: [REFLECT] "Wall thinning is within limits. Valve is acceptable."
Step 7: [ACT]     tool=generate_word_doc, template="approval_note",
                   data={finding: "...", sop_ref: "...", recommendation: "APPROVED"}
Step 8: [DELIVER] approval_note_2026-08-26.docx → user download
```

---

## 9. Coding Agent Architecture

SAGE builds a **native coding agent profile** within the agent engine — not a wrapper around any external CLI tool.

### Why a Native Coding Agent?

| Concern | Native Agent Advantage |
|---------|----------------------|
| **Architecture fit** | ✅ Same Python process, same agent loop, same tool registry as all other agents. |
| **Control** | ✅ Full control over planning, prompting, and retry logic — customizable per-model. |
| **Model routing** | ✅ Uses SAGE's unified model router → always gets the best coding model. |
| **Audit logging** | ✅ Every file read/write, code execution, and test run is logged through SAGE's audit system. |
| **Sandbox** | ✅ Code execution goes through SAGE's Docker sandbox with network isolation. |

### Coding Agent Profile

```python
# agent/profiles/coder.py
CODER_PROFILE = AgentProfile(
    name="coder",
    description="Coding agent for code generation, debugging, and execution",
    model_capability="coding",  # Routes to coding-specialized model
    tools=[
        "read_file", "write_file", "list_directory",
        "execute_code", "run_shell",
        "lint_check", "run_tests",
    ],
    system_prompt="You are a coding agent. Write, execute, test, and verify code...",
    max_steps=20,
)
```

### Coding Workflow Loop

```
User request → "Write a Python function to parse CSV and calculate averages"
    │
    ▼
[PLAN]     Break into: write code → execute → check output → fix if needed → deliver
    │
    ▼
[ACT]      tool=write_file, path="solution.py", content=<generated code>
    │
    ▼
[ACT]      tool=execute_code, file="solution.py", sandbox=true
    │
    ▼
[OBSERVE]  Execution result: error on line 12 / success with output
    │
    ▼
[REFLECT]  Error? → fix and retry. Success? → verify output correctness.
    │
    ▼
[DELIVER]  Working code file → user download
```

This gives full control, full audit logging, and unified model routing.

---

## 10. Model Server Selection: vLLM vs Alternatives

### Decision Matrix

| Criterion | vLLM | llama.cpp server | SGLang |
|-----------|------|-------------------|--------|
| **Setup complexity** | ⭐⭐⭐ Docker + config | ⭐⭐⭐⭐ Single binary | ⭐⭐⭐ Docker + config |
| **Multi-platform** | ⚠️ Linux only (Docker on others) | ✅ Win/Mac/Linux native | ⚠️ Linux only |
| **Concurrent users** | ✅ Continuous batching | ⚠️ Limited batching | ✅ Continuous batching |
| **Model format** | Safetensors (full/AWQ/GPTQ) + GGUF | GGUF (quantized) | Safetensors + GGUF |
| **VRAM efficiency** | ⭐⭐⭐⭐⭐ PagedAttention | ⭐⭐⭐ Good (Q4 quants) | ⭐⭐⭐⭐⭐ RadixAttention |
| **Vision model support** | ✅ Native | ⚠️ Partial (model-dependent) | ✅ Native |
| **OpenAI-compatible API** | ✅ Built-in | ✅ Built-in | ✅ Built-in |
| **Air-gap deployment** | ⚠️ Docker + Python deps | ✅ Simple binary + model files | ⚠️ Docker + Python deps |
| **Production readiness** | ⭐⭐⭐⭐⭐ Enterprise-grade | ⭐⭐⭐ Good for small scale | ⭐⭐⭐⭐ Production-ready |
| **Multi-model serving** | ✅ Native | ⚠️ Separate processes | ✅ Native |

### Recommendation: Dual-Stack Strategy

**SIH Demo & MVP:** Use **llama.cpp server** (`llama-server`)

**Rationale:**
1. **Cross-platform** — Single binary runs on Windows/Mac/Linux. Judges may have any OS.
2. **GGUF quantization** — Essential for fitting models on a 16-24GB GPU.
3. **Lightweight** — No Docker, no Python runtime, no heavy dependencies.
4. **Fast startup** — Model loaded and serving in seconds.
5. **OpenAI-compatible API** — Same `/v1/chat/completions` endpoint as vLLM.

**Production Scale-up:** Use **vLLM**

**Rationale:**
1. **Continuous batching** — Handles 10-100+ concurrent users efficiently.
2. **PagedAttention** — Best-in-class VRAM efficiency.
3. **Multi-model serving** — Serve multiple models from a single process.
4. **FP8/AWQ quantization** — Better quality than GGUF at similar compression.
5. **Enterprise-grade** — Battle-tested at scale.

### Abstract Interface — Swap Backends Without Code Changes

```python
# Abstract interface — both backends expose OpenAI-compatible API
class ModelClient(Protocol):
    async def chat(self, model: str, messages: list, tools: list | None) -> Response: ...
    async def generate(self, model: str, prompt: str, images: list | None) -> Response: ...

class LlamaCppClient(ModelClient): ...   # SIH Demo & MVP
class VLLMClient(ModelClient): ...       # Production scale-up
```

Both llama.cpp server and vLLM expose the same OpenAI-compatible `/v1/chat/completions` endpoint, so the `ModelClient` implementation is nearly identical — just a different base URL.

### When to Upgrade from llama.cpp to vLLM

- More than ~5 concurrent users
- Need for continuous batching (throughput > latency)
- Running on dedicated Linux GPU server with 48GB+ VRAM
- Need FP8/AWQ quantization instead of GGUF
- Need multi-model serving from a single process

---

> **Cross-References:**
> - Architecture & Foundation → `01_Architecture_And_Foundation.md`
> - Tool/Plugin & RAG details → `03_Tools_RAG_And_Multimodal.md`
> - Backend, Frontend & Security → `04_Backend_Frontend_And_Security.md`
> - Development Phases & Demo → `05_Development_Phases_And_Demo_Strategy.md`
> - Hardware, Testing & Deployment → `06_Hardware_Testing_And_Deployment.md`
