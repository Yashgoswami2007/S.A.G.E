import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from sage.config import settings
from sage.auth.middleware import AuthMiddleware
from sage.api import health, auth, admin, chat, tasks
from sage.models.lifecycle import ModelLifecycleManager

logger = logging.getLogger("sage")

# Initialize ModelLifecycleManager using the globally accessible model_registry from chat router
lifecycle_manager = ModelLifecycleManager(chat.model_registry)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SAGE backend (Phase 2a Model Serving active)...")
    await lifecycle_manager.start_all()
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
