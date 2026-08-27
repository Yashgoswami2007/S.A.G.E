import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from sage.config import settings
from sage.auth.middleware import AuthMiddleware
from sage.api import health, auth, admin, chat, tasks

logger = logging.getLogger("sage")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SAGE backend (Phase 1 Agent Core active)...")
    yield
    logger.info("Shutting down SAGE backend...")

app = FastAPI(
    title="SAGE - Sovereign On-Premise Agentic AI Workbench",
    version="0.2.0",
    description="Backend API for SAGE Phase 1 (Agent Core)",
    lifespan=lifespan
)

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
