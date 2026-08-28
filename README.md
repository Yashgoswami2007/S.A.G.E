# SAGE: Sovereign On-Premise Agentic AI Workbench

![SAGE Architecture Status](https://img.shields.io/badge/Architecture-Modular_Monolith-blue)
![Phase 1](https://img.shields.io/badge/Phase-1_(Agent_Core)-brightgreen)
![Python Version](https://img.shields.io/badge/Python-3.12-yellow)

**SAGE** is a highly secure, air-gapped, on-premise AI workbench built for **Mangalore Refinery and Petrochemicals Limited (MRPL)** (SIH Problem Statement 26117). 

SAGE provides a comprehensive multi-model orchestration engine, a deterministic router, a custom ReAct agent loop, and native integrations for both a Next.js Web UI and a Terminal CLI—all guaranteed to operate with **Zero Egress** data sovereignty.

---

## 🏗️ Architecture

SAGE is built as a **Modular Monolith** using **FastAPI** to keep operational overhead low while maintaining clear internal boundaries.

### Core Components
1. **Model Router:** A deterministic router that instantly evaluates tasks by explicit profiles, input modalities, and keyword heuristics, selecting the optimal model (e.g., Coding, Vision, Reasoning) without the latency of an LLM loop.
2. **ReAct Executor Engine:** A highly robust agent loop (`Plan -> Act -> Observe -> Reflect -> Deliver`) with hard limits on steps and retries.
3. **Tool Registry:** Extensible toolkit currently featuring 7 core tools (`read_file`, `write_file`, `list_dir`, `search_files`, `get_file_info`, `apply_patch`, `execute_command`).
4. **Agent Profiles:** Purpose-built profiles (`analyst`, `coder`, `inspector`, `general`) enforcing precise tool permissions (e.g., safe/read-only vs high-risk execution).
5. **Dual-Frontend Support:** Access SAGE securely via the **Web UI** or the native **SAGE CLI**.

---

## 🚀 Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (if developing locally)

### Option 1: Docker Deployment (Recommended)
You can deploy the entire SAGE stack (Backend + Database + Models) with a single command.
```bash
docker-compose up --build
```

### Option 2: Local Development
To run the SAGE Backend on your host machine for development:

1. **Set up Virtual Environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1
```

2. **Install Dependencies:**
```bash
pip install -r backend/requirements.txt  # (or install manually per backend/pyproject.toml)
```

3. **Run Backend Server:**
```bash
docker-compose -f docker-compose.dev.yml up
# OR natively:
uvicorn sage.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 💻 SAGE CLI

SAGE includes a native terminal CLI tailored for power users and developers.

### Installation
```bash
cd cli
pip install -e .
```

### Usage
Check the health of your connected local inference servers:
```bash
sage health
```

Submit a multi-step task to the Agent Core and watch the live execution trace render directly in your terminal:
```bash
sage ask "List the files in my workspace" --profile coder
```

---

## 🔒 Security & Sovereignty

SAGE operates under a strict **Zero Egress** mandate:
- **No Cloud APIs:** All models (via `llama.cpp` or `vLLM`) run locally.
- **Role-Based Execution:** High-risk shell commands trigger a `WAITING_FOR_APPROVAL` state, ensuring an AI agent can never unilaterally modify critical host environments.
- **Audit Logging:** Every single step, tool call, reasoning reflection, and network packet is logged persistently to the structured database.

---

*Built for Smart India Hackathon (SIH).*
