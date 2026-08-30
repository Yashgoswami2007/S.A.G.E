import asyncio
import os
import shutil
import httpx
import structlog
from typing import Dict, List, Optional
from sage.models.registry import ModelRegistry, ModelConfig

logger = structlog.get_logger(__name__)

# Resolve the llama-server binary path once at import time.
# Checks PATH first; if not found, falls back to the known Windows install location.
_LLAMA_SERVER_FALLBACK = r"C:\llama-b10679-bin-win-cuda-13.3-x64\llama-server.exe"

def _resolve_llama_server() -> str:
    """Return the absolute path to llama-server, searching PATH then known fallbacks."""
    found = shutil.which("llama-server")
    if found:
        return found
    if os.path.isfile(_LLAMA_SERVER_FALLBACK):
        logger.info(f"llama-server not on PATH; using fallback: {_LLAMA_SERVER_FALLBACK}")
        return _LLAMA_SERVER_FALLBACK
    raise FileNotFoundError(
        "llama-server not found on PATH and fallback path does not exist. "
        f"Add it to PATH or install it at {_LLAMA_SERVER_FALLBACK}"
    )

_LLAMA_SERVER_BIN: Optional[str] = None

class ModelLifecycleManager:
    """Manages the startup, health tracking, and shutdown of local model server processes."""
    
    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._health_tasks: Dict[str, asyncio.Task] = {}
        
    async def start_all(self):
        """Starts servers for all configured auto-start models if their GGUF files exist."""
        logger.info("Initializing Model Lifecycle Manager...")
        
        for model in self.registry.list_all():
            if not os.path.exists(model.model_path):
                logger.error(f"Model file not found for {model.id} at {model.model_path}. Marking UNAVAILABLE.")
                model.status = "UNAVAILABLE"
                continue
                
            if model.auto_start:
                await self._start_server(model)
            else:
                logger.info(f"Model {model.id} is configured for on-demand loading.")
                model.status = "UNAVAILABLE"
            
    async def _start_server(self, model: ModelConfig):
        """Spawns a llama-server process for the given model."""
        logger.info(f"Starting {model.server_type} for model: {model.id} on port {model.server_port}")
        
        if model.server_type == "llama-server":
            global _LLAMA_SERVER_BIN
            if _LLAMA_SERVER_BIN is None:
                try:
                    _LLAMA_SERVER_BIN = _resolve_llama_server()
                except FileNotFoundError as e:
                    logger.error(str(e))
                    model.status = "UNAVAILABLE"
                    return
            cmd = [
                _LLAMA_SERVER_BIN,
                "-m", model.model_path,
                "--port", str(model.server_port),
                "-c", str(model.context_length),
                "-ngl", str(model.gpu_layers)
            ]
        elif model.server_type == "vllm":
            cmd = [
                "python", "-m", "vllm.entrypoints.openai.api_server",
                "--model", model.model_path,
                "--port", str(model.server_port),
                "--gpu-memory-utilization", "0.9"
            ]
        else:
            logger.error(f"Unknown server_type: {model.server_type}")
            return
        
        try:
            # We don't pipe stdout/stderr here so it goes to the main console,
            # or we could capture it for debugging if needed.
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            self._processes[model.id] = proc
            model.status = "DEGRADED"  # Starting up, not yet healthy
            
            # Start background health checker
            task = asyncio.create_task(self._health_check_loop(model))
            self._health_tasks[model.id] = task
            
        except Exception as e:
            import traceback
            logger.error(
                f"Failed to start server for {model.id}: {type(e).__name__}: {e}\n"
                + traceback.format_exc()
            )
            model.status = "UNAVAILABLE"
            
    async def _health_check_loop(self, model: ModelConfig):
        """Periodically polls the model server's health endpoint."""
        url = f"http://localhost:{model.server_port}/v1/models"
        
        while True:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        if model.status != "READY":
                            logger.info(f"Model {model.id} is now READY.")
                            model.status = "READY"
                    else:
                        if model.status == "READY":
                            logger.warning(f"Model {model.id} health check failed ({resp.status_code}). Marking DEGRADED.")
                            model.status = "DEGRADED"
            except httpx.ConnectError:
                if model.status == "READY":
                    logger.warning(f"Model {model.id} unreachable. Marking DEGRADED.")
                    model.status = "DEGRADED"
            except Exception:
                pass
                
            # Check if process died
            proc = self._processes.get(model.id)
            if proc and proc.returncode is not None:
                logger.error(f"Model server for {model.id} crashed with exit code {proc.returncode}. Marking UNAVAILABLE.")
                model.status = "UNAVAILABLE"
                break
                
            await asyncio.sleep(5)
            
    async def stop_all(self):
        """Terminates all running model servers."""
        logger.info("Shutting down model servers...")
        
        # Cancel health checks
        for task in self._health_tasks.values():
            task.cancel()
            
        # Terminate processes
        for model_id, proc in self._processes.items():
            if proc.returncode is None:
                logger.info(f"Terminating server for {model_id}...")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"Force killing server for {model_id}...")
                    proc.kill()
                    await proc.wait()
                    
        self._processes.clear()
        self._health_tasks.clear()
        
        for model in self.registry.list_all():
            model.status = "UNAVAILABLE"

    async def start_model(self, model_id: str) -> bool:
        """Starts a specific model on-demand."""
        model = self.registry.models.get(model_id)
        if not model:
            logger.error(f"Model {model_id} not found in registry.")
            return False
            
        if model.status == "READY" or model.status == "DEGRADED":
            logger.info(f"Model {model_id} is already running.")
            return True
            
        if not os.path.exists(model.model_path):
            logger.error(f"Model file not found for {model_id} at {model.model_path}.")
            model.status = "UNAVAILABLE"
            return False
            
        await self._start_server(model)
        
        # Wait up to 30 seconds for the model to become READY
        for _ in range(30):
            if model.status == "READY":
                return True
            await asyncio.sleep(1)
            
        logger.warning(f"Timeout waiting for model {model_id} to become READY.")
        return False
        
    async def stop_model(self, model_id: str) -> bool:
        """Stops a specific running model."""
        model = self.registry.models.get(model_id)
        if not model:
            return False
            
        # Cancel health check
        task = self._health_tasks.pop(model_id, None)
        if task:
            task.cancel()
            
        # Terminate process
        proc = self._processes.pop(model_id, None)
        if proc and proc.returncode is None:
            logger.info(f"Terminating server for {model_id}...")
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                
        model.status = "UNAVAILABLE"
        return True

    async def swap_model(self, load_id: str, unload_id: str) -> bool:
        """Swaps two models to manage VRAM."""
        logger.info(f"Swapping models: unloading {unload_id}, loading {load_id}")
        await self.stop_model(unload_id)
        # Add a short delay to ensure VRAM is cleared
        await asyncio.sleep(2)
        return await self.start_model(load_id)
