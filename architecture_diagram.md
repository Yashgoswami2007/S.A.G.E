# SAGE (Sovereign Agentic AI Workbench) - Complete Architecture Specification

> **Notice**: This architecture document is reverse-engineered directly from the active codebase (`backend/`, `frontend/`, `cli/`, `config/`, `docker-compose.yml`, `run.bat`), completely omitting outdated external specifications.

---

## 1. System Overview & Layered Architecture

```mermaid
graph TB
    subgraph Clients["Client Tier"]
        UI["Modern Web Application\n(TanStack Start / React 19 / Vite / Bun / Tailwind)"]
        CLI["SAGE Terminal CLI\n(Typer / Rich / Python 3.11+)"]
    end

    subgraph EdgeProxy["Frontend Server / API Proxy (Bun / Node Runtime)"]
        ProxyChat["/api/chat (SSE Stream Transformer)"]
        ProxyModels["/api/models (Health & Model Status)"]
        ProxyActivate["/api/models/activate (VRAM Swap)"]
        ProxyConfirm["/api/chat/confirm (HITL Approval)"]
        ProxyUpload["/api/upload (File Ingestion)"]
    end

    subgraph BackendGateway["FastAPI Core Gateway (Port 8000)"]
        direction TB
        MW["Auth Middleware + CORS"]
        Audit["Structured Audit Logger\n(Air-gap Compliance)"]
        ExHandlers["Unified Error Envelope Handlers\n(SAGEError, HTTPException, Validation)"]

        subgraph Routers["API Routers"]
            R_Health["/health"]
            R_Chat["/api/chat (/completions, /stream, /confirm, /ws)"]
            R_Admin["/api/admin (/models, /models/{id}/activate)"]
            R_Tasks["/api/tasks (Status & Results)"]
            R_Upload["/api/upload (Multipart Ingestion)"]
            R_Auth["/api/auth (Tokens & Identity)"]
        end
    end

    subgraph AgentCore["Agent Orchestration Engine"]
        Executor["ReActExecutor\n(Multi-Step Planner + Actor + Reflector)"]
        Planner["Task Planner\n(OpenAI JSON-Schema Tool Planning)"]
        Router["ModelRouter\n(Profile, Modality & Keyword Routing)"]
        Profiles["ProfileManager\n(Analyst, Coder, Inspector, Documentor, General)"]
        StateTrace["ExecutionTrace & TraceEvent Store"]
    end

    subgraph ModelServing["Local Sovereign Model Serving"]
        Lifecycle["ModelLifecycleManager\n(Process Supervisor & Crash Watcher)"]
        Registry["ModelRegistry\n(model_registry.yaml + Auto-Scanner)"]
        GPUDet["GPUDetector\n(VRAM Profiler & Layer Offloading)"]
        CircuitBreaker["Global CircuitBreaker\n(Fail-Fast & Recovery Countdown)"]
        LLMClient["OpenAICompatibleClient\n(Streaming HTTP Client)"]
        
        subgraph Subprocesses["Local Inference Servers (llama-server / vLLM)"]
            Qwen["Primary: Qwen3-8B-Q4_K_M\n(Port 8001 | ~6GB VRAM | Reasoning / General)"]
            Gemma["Fallback / Specialist: Gemma 4 12B IT\n(Port 8002 | ~8GB VRAM | Coding / Vision)"]
        end
    end

    subgraph ToolsAndSandbox["Tools & Execution Sandbox"]
        ToolReg["ToolRegistry\n(18 Core Tools + Strict Schema Validation)"]
        Sandbox["SandboxManager\n(Subprocess Isolation in workspace/sandbox_runs/)"]
        DocGen["Document Generators\n(python-docx, openpyxl, python-pptx)"]
        DocRead["Document Readers & OCR\n(pdfplumber, openpyxl, Tesseract OCR)"]
        FileProc["FileProcessor\n(Multimodal Extractor & Text Chunker)"]
    end

    subgraph Persistence["Storage & Data Infrastructure"]
        PG[("PostgreSQL 16 + pgvector\n(users, audit_logs, chat_sessions, chat_messages)")]
        Redis[("Redis 7 Alpine\n(Heartbeat, Cache & Locks)")]
        FS[("Host Filesystem\n(workspace/, models/, config/, templates/)")]
    end

    %% Client to Edge
    UI --> ProxyChat & ProxyModels & ProxyActivate & ProxyConfirm & ProxyUpload
    CLI --> R_Health & R_Chat

    %% Edge to Backend
    ProxyChat --> R_Chat
    ProxyModels --> R_Admin
    ProxyActivate --> R_Admin
    ProxyConfirm --> R_Chat
    ProxyUpload --> R_Upload

    %% Gateway to Middleware & Routers
    MW --> Routers
    Routers --> Audit
    Routers --> ExHandlers

    %% Routers to Agent & Models
    R_Chat --> Executor
    R_Admin --> Lifecycle
    R_Upload --> FileProc

    %% Agent Engine Interactions
    Executor --> Router
    Executor --> Planner
    Executor --> Profiles
    Executor --> StateTrace
    Executor --> ToolReg
    Executor --> LLMClient
    Router --> Registry

    %% Model Serving
    Lifecycle --> Registry
    Lifecycle --> GPUDet
    Lifecycle --> Subprocesses
    LLMClient --> CircuitBreaker
    CircuitBreaker --> Subprocesses

    %% Tools & Sandbox
    ToolReg --> Sandbox
    ToolReg --> DocGen
    ToolReg --> DocRead
    FileProc --> FS
    Sandbox --> FS

    %% Persistence
    BackendGateway --> PG
    BackendGateway --> Redis
    BackendGateway --> FS
```

---

## 2. ReAct Agent Execution Loop & Event Streaming

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client UI
    participant WebProxy as /api/chat Proxy
    participant ChatAPI as FastAPI /api/chat/stream
    participant Executor as ReActExecutor
    participant Router as ModelRouter
    participant Lifecycle as ModelLifecycleManager
    participant Planner as TaskPlanner
    participant LLM as llama-server (Active Model)
    participant ToolReg as ToolRegistry
    participant Sandbox as SandboxManager

    User->>WebProxy: POST /api/chat (prompt, profile, attachments)
    WebProxy->>ChatAPI: Forward StreamRequest
    ChatAPI->>Executor: run(prompt, profile, file_attachments)

    Note over Executor,Router: 1. Model Selection & Modality Detection
    Executor->>Router: route(prompt, profile, attachments)
    Router-->>Executor: Selected ModelConfig (e.g. Qwen3-8B) + reason

    opt Requires VRAM Swap (e.g., target model UNAVAILABLE)
        Executor->>Lifecycle: swap_model(load_id, unload_id)
        Lifecycle->>LLM: Terminate current server -> Load target server
        Lifecycle-->>Executor: Target server READY
    end

    Note over Executor,ChatAPI: 2. State: PLANNING
    Executor->>Planner: create_plan(prompt, tools, client)
    Planner->>LLM: JSON-schema constrained plan prompt
    LLM-->>Planner: Plan JSON: {summary, steps: [{step_id, tool, args}]}
    Planner-->>Executor: Structured Plan object
    Executor->>ChatAPI: Emit TraceEvent(PLAN_CREATED)
    ChatAPI-->>User: SSE: data: {"type": "PLAN_CREATED", ...}

    Note over Executor,ToolReg: 3. Execution Loop (State: ACTING)
    loop For each step in Plan (up to max_steps=15)
        alt Step requires High-Risk Tool (e.g. execute_command)
            Executor->>ChatAPI: Emit TraceEvent(CONFIRMATION_REQUIRED)
            ChatAPI-->>User: SSE: data: {"type": "CONFIRMATION_REQUIRED", "request_id": "..."}
            User->>ChatAPI: POST /api/chat/confirm {request_id, approved: true}
            ChatAPI-->>Executor: Unblock confirmation event
        end

        Executor->>ToolReg: execute(tool_name, tool_args)
        alt Code / Script Tool
            ToolReg->>Sandbox: execute_code(code, language)
            Sandbox->>Sandbox: Subprocess run in workspace/sandbox_runs/<id>
            Sandbox-->>ToolReg: SandboxResult(stdout, stderr, exit_code)
        else File / Document Tool
            ToolReg->>ToolReg: File I/O inside WORKSPACE_DIR
        end
        ToolReg-->>Executor: ToolResult(success, output, error)
        Executor->>ChatAPI: Emit TraceEvent(TOOL_RESULT)
        ChatAPI-->>User: SSE: data: {"type": "TOOL_RESULT", ...}
    end

    Note over Executor,LLM: 4. Final Synthesis & Token Streaming
    Executor->>LLM: Stream completion prompt + synthesized tool outputs
    loop Token Streaming
        LLM-->>Executor: token chunk
        Executor->>ChatAPI: Emit TraceEvent(TOKEN)
        ChatAPI-->>User: SSE: data: {"type": "TOKEN", "token": "..."}
    end

    Executor->>ChatAPI: Emit FinalEvent(content=final_output)
    ChatAPI-->>User: SSE: data: {"type": "FINAL", "content": "..."}
    ChatAPI-->>User: SSE: data: [DONE]
```

---

## 3. Model Serving, VRAM Lifecycle & Circuit Breaker Architecture

```mermaid
stateDiagram-v2
    [*] --> Discovered: System Startup / Scan

    state "Model Registry" as RegistryState {
        Discovered --> UNAVAILABLE: Model binary (.gguf) verified
        UNAVAILABLE --> Spawning: auto_start=true OR swap_model()
        Spawning --> READY: HTTP GET /health returns 200 within 60s
        Spawning --> UNAVAILABLE: Timeout / Binary Missing / Spawn Error
        READY --> DEGRADED: Health check fail / Process Unresponsive
        DEGRADED --> READY: Health check recovers
        DEGRADED --> UNAVAILABLE: Process terminates (returncode != None)
        READY --> Stopping: swap_model(unload) OR shutdown
        Stopping --> UNAVAILABLE: SIGTERM / SIGKILL complete
    }

    state "VRAM Swap Orchestration (RTX Single GPU)" as SwapState {
        direction LR
        UnloadCurrent: 1. Terminate running model process
        WaitVRAM: 2. Sleep 2.0s to allow GPU memory release
        SpawnTarget: 3. Launch target llama-server with --gpu-layers
        VerifyReady: 4. Poll health endpoint until READY
        
        UnloadCurrent --> WaitVRAM
        WaitVRAM --> SpawnTarget
        SpawnTarget --> VerifyReady
    }

    state "Circuit Breaker State Machine" as CBState {
        CLOSED --> OPEN: Failure threshold reached (5 consecutive fails)
        OPEN --> HALF_OPEN: Recovery timeout expires (30.0s countdown)
        HALF_OPEN --> CLOSED: Test probe request succeeds
        HALF_OPEN --> OPEN: Test probe request fails
    }

    UNAVAILABLE --> SwapState: on_demand / profile request
    READY --> CBState: Inbound inference traffic
```

---

## 4. Tool Registry, Permissions & Sandboxing Architecture

```mermaid
classDiagram
    class BaseTool {
        +str name
        +str description
        +Dict parameters
        +ToolPermission permission
        +execute(**kwargs) ToolResult
        +to_openai_schema() Dict
    }

    class ToolPermission {
        <<enumeration>>
        SAFE (Read-only operations)
        MODIFY (File writes / Document generation)
        HIGH_RISK (Code execution / Shell commands)
    }

    class ToolResult {
        +bool success
        +str output
        +Optional~str~ error
        +Optional~Dict~ metadata
    }

    class ToolRegistry {
        -Dict~str, BaseTool~ _tools
        +register(tool)
        +get_tool(name) BaseTool
        +list_tools(allowed, max_perm) List~BaseTool~
        +get_openai_schemas() List~Dict~
        -_validate_tool_args(tool, kwargs) ToolResult
    }

    class SandboxManager {
        -Path _sandbox_dir
        -Dict~str, Process~ _running
        +execute_code(code, language, working_dir) SandboxResult
        +execute_command(command, working_dir) SandboxResult
        +run_script(script_path, args) SandboxResult
        +cancel(sandbox_id) bool
    }

    BaseTool <|-- ReadFileTool
    BaseTool <|-- WriteFileTool
    BaseTool <|-- ListDirTool
    BaseTool <|-- SearchFilesTool
    BaseTool <|-- ApplyPatchTool
    BaseTool <|-- ExecuteCommandTool
    BaseTool <|-- ExecuteCodeTool
    BaseTool <|-- RunScriptTool
    BaseTool <|-- ReadPDFTool
    BaseTool <|-- ReadDocxTool
    BaseTool <|-- ReadXlsxTool
    BaseTool <|-- ReadImageTool
    BaseTool <|-- OCRExtractTool
    BaseTool <|-- GenerateDocxTool
    BaseTool <|-- GenerateXlsxTool
    BaseTool <|-- GeneratePptxTool
    BaseTool <|-- CalculatorTool

    ToolRegistry o-- BaseTool
    ExecuteCommandTool ..> SandboxManager : delegates
    ExecuteCodeTool ..> SandboxManager : delegates
    RunScriptTool ..> SandboxManager : delegates
    BaseTool --> ToolPermission
    BaseTool --> ToolResult
```

### Registered Tool Inventory by Permission Tier

| Permission Level | Tools | Description & Safety Invariant |
| :--- | :--- | :--- |
| **SAFE** | `read_file`, `list_dir`, `search_files`, `get_file_info`, `read_pdf`, `read_docx`, `read_xlsx`, `read_image`, `ocr_extract`, `calculator` | Read-only access constrained to `WORKSPACE_DIR`. Directory traversal strictly rejected. |
| **MODIFY** | `write_file`, `apply_patch`, `generate_docx`, `generate_xlsx`, `generate_pptx` | Mutation constrained within `WORKSPACE_DIR`. Automated rollback on patch conflict. |
| **HIGH_RISK** | `execute_command`, `execute_code`, `run_script` | Isolated subprocess in `workspace/sandbox_runs/<id>`. Triggers human-in-the-loop approval if `require_approval_for_high_risk=True`. |

---

## 5. Multimodal Ingestion & Dynamic Routing Pipeline

```mermaid
flowchart TD
    A["Inbound Request (Prompt + Attachments)"] --> B{"Has Attachments?"}
    
    B -- Yes --> C["FileProcessor.process_multiple()"]
    B -- No --> D["Evaluate Prompt Text"]

    C --> C1{"File Type"}
    C1 -- ".pdf" --> E1["PDF Text Extractor (pdfplumber)"]
    C1 -- ".docx" --> E2["Word Docx Extractor (python-docx)"]
    C1 -- ".xlsx / .xls" --> E3["Spreadsheet Reader (openpyxl)"]
    C1 -- ".png, .jpg, .webp" --> E4["Image Base64 URI Encoder"]
    C1 -- Code / PlainText --> E5["UTF-8 Text Extractor (Max 20K chars)"]

    E1 & E2 & E3 & E5 --> F1["Build Context String (Injected into Prompt)"]
    E4 --> F2["Collect Vision Images List"]

    F1 & F2 & D --> G["ModelRouter.route()"]

    G --> H1{"Explicit Profile?"}
    H1 -- "coder" --> M1["Gemma 4 12B IT (Coding Specialist)"]
    H1 -- "inspector" --> M2["Gemma 4 12B IT (Vision Specialist)"]
    H1 -- "analyst / documentor / general" --> M3["Qwen3-8B (Reasoning Specialist)"]
    H1 -- "auto / None" --> H2{"Modality Check"}

    H2 -- "Images Attached / Keywords (image, photo, diagram)" --> M2
    H2 -- "Coding Keywords (code, python, refactor, bug, def)" --> M1
    H2 -- "Default Fallback" --> M3
```

---

## 6. Data Model & Physical Persistence Topology

```mermaid
erDiagram
    users ||--o{ chat_sessions : owns
    users {
        string id PK
        string username UK
        string password_hash
        string role
        datetime created_at
    }

    chat_sessions ||--o{ chat_messages : contains
    chat_sessions {
        string id PK
        string user_id FK
        string profile
        datetime created_at
    }

    chat_messages {
        string id PK
        string session_id FK
        string role "user | assistant | system | tool"
        string content
        datetime created_at
    }

    audit_logs {
        string id PK
        datetime timestamp
        string event_type
        string user_id
        string session_id
        json data_json
    }

    workspace_fs ||--o{ sandbox_runs : generates
    workspace_fs {
        dir uploads "Temporary user uploads"
        dir templates "Document template files (DOCX/XLSX/PPTX)"
        dir sandbox_runs "Isolated temporary execution folders"
        dir models "Local GGUF weights files"
    }
```
