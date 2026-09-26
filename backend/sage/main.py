import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# Windows: force UTF-8 stdio before any logging (cp1252 cannot encode emoji in LLM output).
from sage.core.utils import configure_stdio_encoding
configure_stdio_encoding()

# Windows requires ProactorEventLoop to support asyncio subprocesses.
# SelectorEventLoop (the default on Windows) raises NotImplementedError
# when asyncio.create_subprocess_exec is called.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from sage.config import settings
from sage.auth.middleware import AuthMiddleware
from sage.core.exceptions import SAGEError
from sage.api import health, auth, admin, chat, tasks, upload, workspace, system_stats
from sage.api import settings as settings_router
from sage.api import rag
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
    
    # Initialize workspace manager
    try:
        from sage.workspace import init_workspace_manager
        init_workspace_manager()
        from sage.workspace import workspace_manager
        info = workspace_manager.get_workspace_info()
        logger.info(
            "SAGE Workspace:\n"
            f"  Default: {info.default_workspace}\n"
            f"  Active:  {info.active_workspace}\n"
            f"  Mode:    {info.mode}"
        )
    except Exception as exc:
        logger.error(f"Failed to initialize workspace manager: {exc}")

    try:
        import sage.rag.queue as q
        q.indexing_queue = q.IndexingQueue()
        await q.indexing_queue.start()
    except Exception as exc:
        logger.error(f"Failed to start RAG indexing queue: {exc}")

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
    
    try:
        import sage.rag.queue as q
        if q.indexing_queue:
            await q.indexing_queue.stop()
    except Exception as exc:
        logger.error(f"Failed to stop RAG indexing queue: {exc}")
        
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
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(workspace.router, prefix="/api/workspace", tags=["workspace"])
app.include_router(system_stats.router, prefix="/api/system/stats", tags=["system"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])

# Global Exception Handlers
@app.exception_handler(SAGEError)
async def sage_error_handler(request: Request, exc: SAGEError):
    logger.warning("SAGEError [%s] on %s %s: %s", exc.code, request.method, request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.to_dict(),
            "detail": exc.message,
        },
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning("HTTPException [%s] on %s %s: %s", exc.status_code, request.method, request.url.path, exc.detail)
    code_name = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }.get(exc.status_code, f"HTTP_{exc.status_code}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code_name,
                "message": str(exc.detail),
                "status_code": exc.status_code,
                "details": {},
            },
            "detail": str(exc.detail),
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    msg = "; ".join(f"{'.'.join(str(l) for l in err.get('loc', []))}: {err.get('msg')}" for err in errors)
    logger.warning("ValidationError on %s %s: %s", request.method, request.url.path, msg)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Input validation failed: {msg}",
                "status_code": 422,
                "details": {"errors": errors},
            },
            "detail": f"Input validation failed: {msg}",
        },
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred while processing your request.",
                "status_code": 500,
                "details": {"exception_type": type(exc).__name__, "message": str(exc)},
            },
            "detail": f"Internal server error: {str(exc)}",
        },
    )

