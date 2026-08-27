---
name: sage_backend_frontend_and_security
description: Guides FastAPI backend routes/middleware, Next.js UI structure, JWT authentication, structured audit logging, and firewall-based air-gapped isolation rules.
---
# SAGE — Section 4: Backend, Frontend & Security

**SIH Problem Statement:** SIH26117 — Sovereign On-Premise Agentic AI Workbench  
**Sponsoring Organization:** Mangalore Refinery and Petrochemicals Limited (MRPL)  
**Date:** 2026-08-26

---

## 16. Backend Architecture

### FastAPI Application Structure

```python
# main.py
from fastapi import FastAPI
from sage.api import chat, tasks, documents, admin, auth
from sage.middleware import AuditMiddleware, AuthMiddleware

app = FastAPI(title="SAGE", version="1.0.0")

# Middleware (order matters)
app.add_middleware(AuditMiddleware)     # Log every request
app.add_middleware(AuthMiddleware)      # Authenticate requests

# Routes
app.include_router(auth.router, prefix="/api/auth")
app.include_router(chat.router, prefix="/api/chat")
app.include_router(tasks.router, prefix="/api/tasks")
app.include_router(documents.router, prefix="/api/documents")
app.include_router(admin.router, prefix="/api/admin")

# WebSocket for streaming
app.include_router(chat.ws_router, prefix="/ws")
```

### Key Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/auth/login` | Authenticate user |
| `POST` | `/api/chat/message` | Send message to agent |
| `WS` | `/ws/chat/{session_id}` | Stream agent responses |
| `GET` | `/api/tasks/{task_id}` | Get task status |
| `GET` | `/api/tasks/{task_id}/steps` | Get execution steps (audit) |
| `GET` | `/api/documents/{doc_id}/download` | Download generated document |
| `POST` | `/api/admin/ingest` | Ingest documents into RAG |
| `GET` | `/api/admin/models` | List available models |
| `GET` | `/api/admin/network-log` | View network activity log |
| `GET` | `/api/admin/audit-log` | View audit trail |

### Streaming Architecture

```
Browser ◄──── WebSocket ────► FastAPI ◄──── HTTP SSE ────► Model Server (vLLM / llama.cpp)
         (token-by-token)              (token-by-token)
```

Agent responses stream token-by-token to the UI via WebSocket. Tool calls and results are sent as structured JSON messages interleaved with the stream.

---

## 17. Frontend / UI Architecture

### Technology: Next.js 14+ with App Router

### Page Structure

```
app/
├── layout.tsx              # Root layout with sidebar
├── page.tsx                # Dashboard / home
├── login/page.tsx          # Authentication
├── chat/
│   └── [sessionId]/page.tsx  # Main chat + agent interface
├── documents/
│   └── page.tsx            # Document browser + download
├── knowledge/
│   └── page.tsx            # RAG knowledge base management
├── admin/
│   ├── models/page.tsx     # Model management
│   ├── audit/page.tsx      # Audit log viewer
│   └── network/page.tsx    # Network activity monitor
└── components/
    ├── ChatWindow.tsx       # Main chat component
    ├── AgentSteps.tsx       # Shows agent thinking/planning steps
    ├── ToolCallCard.tsx     # Shows tool execution + results
    ├── DocumentPreview.tsx  # Preview generated docs
    ├── NetworkMonitor.tsx   # Real-time network activity
    └── ModelSelector.tsx    # Model routing indicator
```

### Key UI Features

1. **Chat Interface** — Standard chat with streaming responses.
2. **Agent Transparency Panel** — Shows the agent's plan, current step, tool calls, and reasoning. This is critical for the SIH demo to demonstrate agentic behavior.
3. **Document Preview** — Inline preview of generated Word/PPTX/XLSX files.
4. **Network Monitor** — Real-time display of all network connections, proving sovereignty.
5. **Audit Trail** — Searchable log of all agent actions, model calls, and tool executions.
6. **Model Indicator** — Shows which model is being used for each response.

### Design Aesthetic

- **Dark mode** default (industrial/professional feel)
- **Glassmorphism** cards for agent steps
- **Color-coded** tool calls (green = success, amber = retry, red = error)
- **Animated** thinking/planning indicators
- **Monospace font** for code and logs

---

## 18. Authentication & Authorization

### MVP: Simple JWT Auth

For SIH demo and initial deployment, keep it simple:

```python
# auth/service.py
class AuthService:
    def login(self, username: str, password: str) -> TokenPair:
        user = self.db.get_user(username)
        if not user or not bcrypt.verify(password, user.password_hash):
            raise AuthError("Invalid credentials")
        return TokenPair(
            access_token=jwt.encode({"sub": user.id, "role": user.role}, SECRET),
            refresh_token=jwt.encode({"sub": user.id, "type": "refresh"}, SECRET)
        )
```

### Roles

| Role | Permissions |
|------|------------|
| `user` | Chat, view own history, download own documents |
| `analyst` | User + ingest documents, manage knowledge base |
| `admin` | All + manage models, view audit logs, manage users |

### Production Enhancement

For production deployment in a defence/PSU environment, integrate with:
- **LDAP/Active Directory** (most likely already deployed)
- **Keycloak** (if SSO is required)

---

## 19. Audit Logging

### What Gets Logged

| Event | Fields Captured |
|-------|----------------|
| **User action** | user_id, action, timestamp, IP, session |
| **Agent step** | step_type, model_used, prompt_hash, latency |
| **Tool call** | tool_name, parameters (sanitized), result_summary, duration |
| **Model inference** | model_id, prompt_tokens, completion_tokens, latency |
| **File operation** | operation (read/write/delete), path, size, user_id |
| **Network activity** | destination_ip, port, protocol, bytes, blocked? |
| **Auth event** | login/logout, success/failure, user_id, IP |

### Log Format

```json
{
  "timestamp": "2026-08-26T15:01:33+05:30",
  "level": "INFO",
  "event": "tool_call",
  "session_id": "abc-123",
  "user_id": "user_01",
  "data": {
    "tool": "rag_search",
    "query": "V-301 wall thinning SOP",
    "results_count": 3,
    "latency_ms": 245
  }
}
```

### Storage

- **Hot logs:** PostgreSQL `audit_logs` table (searchable, queryable)
- **Cold logs:** JSON files rotated daily in `/var/log/sage/`
- **Retention:** Configurable (default: 90 days in DB, 1 year on disk)

---

## 20. Network Isolation / Air-Gapped Architecture

### Network Architecture

```
┌──────────────────── SAGE HOST ────────────────────┐
│                                                     │
│   ┌─────────────────────────────────────────┐      │
│   │  iptables / nftables rules:              │      │
│   │  - ALLOW localhost:* ↔ localhost:*        │      │
│   │  - ALLOW internal_network:* (optional)   │      │
│   │  - DROP ALL outbound to 0.0.0.0/0        │      │
│   │  - LOG all blocked connections           │      │
│   └─────────────────────────────────────────┘      │
│                                                     │
│   ┌─────────────────────────────────────────┐      │
│   │  Network Monitor Daemon                  │      │
│   │  - tcpdump logging all interfaces        │      │
│   │  - Alerts on any external connection     │      │
│   │  - Dashboard feed via WebSocket          │      │
│   └─────────────────────────────────────────┘      │
│                                                     │
│   ┌──────────────────────────────────────────┐     │
│   │  SAGE Application                         │     │
│   │  (all connections are localhost only)     │     │
│   └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

### Air-Gap Deployment Procedure

```bash
# On internet-connected machine (preparation):
1. Pull all Docker images
2. Download all GGUF model files (from HuggingFace)
3. Download llama.cpp server binary (or vLLM Docker image)
4. Download all Python/npm packages
5. Bundle everything into a tarball

# On air-gapped machine:
1. Transfer tarball via USB/secure media
2. Load Docker images: docker load < sage-images.tar
3. Copy GGUF model files to /opt/sage/models/
4. Install Python packages from local wheelhouse
5. npm install from local cache
6. Run: docker compose up
7. Verify: sage-admin verify-airgap
```

### `sage-admin verify-airgap` Command

This command:
1. Starts a 60-second `tcpdump` capture.
2. Runs a sample agent workflow.
3. Analyzes the capture for any non-localhost traffic.
4. Generates a sovereignty verification report.

---

## 21. Security Threat Model

| Threat | Severity | Mitigation |
|--------|----------|------------|
| **Data exfiltration via model** | CRITICAL | Models are local, no API calls, network blocked |
| **Prompt injection** | HIGH | Input sanitization, tool result validation, structured outputs |
| **Sandbox escape** | HIGH | Docker isolation, seccomp, resource limits, no network |
| **Unauthorized access** | HIGH | JWT auth, role-based access, audit logging |
| **Model poisoning** | MEDIUM | Model checksums verified at load time |
| **Denial of service** | MEDIUM | Rate limiting, execution timeouts, resource quotas |
| **Supply chain attack** | MEDIUM | Pin all dependency versions, verify checksums |
| **Log tampering** | MEDIUM | Append-only log files, hash chain |
| **Path traversal** | MEDIUM | All file paths validated against allowed directories |
| **LLM hallucination** | MEDIUM | RAG with source attribution, human-in-the-loop for critical outputs |
