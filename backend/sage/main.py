import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# Windows requires ProactorEventLoop to support asyncio subprocesses.
# SelectorEventLoop (the default on Windows) raises NotImplementedError
# when asyncio.create_subprocess_exec is called.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from sage.config import settings
from sage.api import health, auth, admin, chat, tasks, rag
from sage.auth.middleware import AuthMiddleware
from sage.models.lifecycle import ModelLifecycleManager

from sage.models.registry import ModelRegistry

logger = logging.getLogger("sage")

# Initialize ModelLifecycleManager — tolerant of missing/corrupt registry files.
# If the registry can't be loaded, the manager is still created (with an empty
# registry) and the router's hardcoded fallback model will serve requests.
try:
    lifecycle_manager = ModelLifecycleManager(ModelRegistry(settings.MODEL_REGISTRY_PATH))
except Exception as exc:
    logger.warning(
        "Failed to initialise ModelLifecycleManager: %s. "
        "The server will start without managed models — LLM responses will use the router fallback.",
        exc,
    )
    # Create a lifecycle manager with an empty registry so the rest of the app doesn't NPE
    lifecycle_manager = ModelLifecycleManager(ModelRegistry.__new__(ModelRegistry))
    lifecycle_manager.registry.models = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SAGE backend (Phase 2a Model Serving active)...")
    try:
        await lifecycle_manager.start_all()
    except Exception as exc:
        logger.warning(
            "Model startup failed: %s. "
            "Continuing without model servers — the router will use its hardcoded fallback.",
            exc,
        )
    yield
    logger.info("Shutting down SAGE backend...")
    await lifecycle_manager.stop_all()

app = FastAPI(
    title="SAGE - Sovereign On-Premise Agentic AI Workbench",
    version="0.2.0",
    description="Backend API for SAGE Phase 2",
    lifespan=lifespan
)
app.state.lifecycle_manager = lifecycle_manager

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth Middleware
app.add_middleware(AuthMiddleware)

# API Routers
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])

