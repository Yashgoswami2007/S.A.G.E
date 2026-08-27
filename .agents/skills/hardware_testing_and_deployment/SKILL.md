---
name: sage_hardware_testing_and_deployment
description: Guides hardware sizing (RTX 3060 to A100), model sizing/quantization choices, model configuration extensions, testing guidelines, failure mitigation logic, performance tuning, local docker/firewall deployment, and sovereignty proofs.
---
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

> [!NOTE]
> For supplementary architectural diagrams, risks and mitigations list, list of pitfalls to avoid, and the project proposed changes/verification plans, see:
> [architecture_details.md](file:///.agents/skills/hardware_testing_and_deployment/references/architecture_details.md)
