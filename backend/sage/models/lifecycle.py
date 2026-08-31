import asyncio
import os
import shutil
import httpx
import structlog
from typing import Dict, List, Optional
from sage.models.registry import ModelRegistry, ModelConfig
from sage.models.gpu_detector import detect_gpus, GPUStatus

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
        # Track which fallback activations are already in-flight to avoid duplicates
        self._fallback_in_progress: set = set()
        # GPU status — populated on start_all()
        self.gpu_status: Optional[GPUStatus] = None
        
    async def start_all(self):
        """Starts servers for all configured auto-start models if their GGUF files exist."""
        logger.info("Initializing Model Lifecycle Manager...")
        
        # ── Detect GPUs once at startup ───────────────────────────────────
        self.gpu_status = detect_gpus()
        self._log_gpu_banner()
        
        for model in self.registry.list_all():
            if not os.path.exists(model.model_path):
                logger.error(f"Model file not found for {model.id} at {model.model_path}. Marking UNAVAILABLE.")
                model.status = "UNAVAILABLE"
                # Fire-and-forget: attempt to start fallback after a short settle delay
                asyncio.create_task(self._activate_fallback(model.id))
                continue
                
            if model.auto_start:
                await self._start_server(model)
            else:
                logger.info(f"Model {model.id} is configured for on-demand loading.")
                model.status = "UNAVAILABLE"

        # After spawning all auto-start servers, wait up to 60 s for each to become
        # READY and trigger fallback for any that never make it.
        asyncio.create_task(self._watch_startup_and_fallback())

    def _log_gpu_banner(self):
        """Log a clear startup banner showing GPU status."""
        if self.gpu_status and self.gpu_status.cuda_available:
            for gpu in self.gpu_status.gpus:
                logger.info(
                    f"[GPU] CUDA available: True | "
                    f"{gpu.name} ({gpu.vram_total_mb} MB total, {gpu.vram_free_mb} MB free) | "
                    f"Driver: {self.gpu_status.driver_version} | CUDA: {self.gpu_status.cuda_version}"
                )
        else:
            logger.info("[GPU] CUDA not available — all models will run in CPU-only mode (slower)")

    def _resolve_gpu_layers(self, model: ModelConfig) -> int:
        """
        Determine the effective gpu_layers value for a model based on:
        - The model's gpu_mode ("auto" / "gpu" / "cpu")
        - The global GPU_MODE override from settings
        - Whether CUDA is available
        - Whether free VRAM is sufficient (free VRAM >= min_vram_gb)

        Returns:
            int: 99 for full GPU offload, 0 for CPU-only.
            Raises RuntimeError for gpu_mode="gpu" when no CUDA is available.
        """
        # Import settings lazily to avoid circular imports at module level
        from sage.config import settings

        # Global override takes precedence over per-model setting
        effective_mode = settings.GPU_MODE if settings.GPU_MODE != "auto" else model.gpu_mode

        gpu_status = self.gpu_status or GPUStatus(
            cuda_available=False, gpu_count=0, gpus=[], driver_version="", cuda_version=""
        )

        if effective_mode == "cpu":
            logger.info(f"Model {model.id}: gpu_mode=cpu → ngl=0 (CPU-only)")
            return 0

        if effective_mode == "gpu":
            if not gpu_status.cuda_available:
                logger.error(
                    f"Model {model.id}: gpu_mode=gpu but no CUDA GPU detected — cannot start"
                )
                raise RuntimeError(f"gpu_mode=gpu requires CUDA but no GPU found for {model.id}")
            logger.info(f"Model {model.id}: gpu_mode=gpu → ngl=99 (forced GPU offload)")
            return 99

        # effective_mode == "auto"
        if not gpu_status.cuda_available:
            logger.info(f"Model {model.id}: gpu_mode=auto, no CUDA → ngl=0 (CPU fallback)")
            return 0

        # CUDA is available — check VRAM fit
        # Use the GPU with the most free VRAM
        best_gpu = max(gpu_status.gpus, key=lambda g: g.vram_free_mb)
        required_mb = model.min_vram_gb * 1024
        if best_gpu.vram_free_mb >= required_mb:
            logger.info(
                f"Model {model.id}: gpu_mode=auto, "
                f"needs {model.min_vram_gb} GB, "
                f"{best_gpu.vram_free_mb} MB free on {best_gpu.name} "
                f"→ ngl=99 (GPU offload)"
            )
            return 99
        else:
            logger.warning(
                f"Model {model.id}: gpu_mode=auto, "
                f"needs {model.min_vram_gb} GB ({required_mb} MB) but only "
                f"{best_gpu.vram_free_mb} MB free on {best_gpu.name} "
                f"→ ngl=0 (CPU fallback — insufficient VRAM)"
            )
            return 0

    async def _start_server(self, model: ModelConfig):
        """Spawns a llama-server process for the given model."""
        logger.info(f"Starting {model.server_type} for model: {model.id} on port {model.server_port}")

        # ── Resolve GPU layers ────────────────────────────────────────────
        try:
            effective_ngl = self._resolve_gpu_layers(model)
        except RuntimeError:
            model.status = "UNAVAILABLE"
            return
        
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
                "-ngl", str(effective_ngl)
            ]
        elif model.server_type == "vllm":
            # vLLM requires a CUDA GPU — cannot run CPU-only
            if not (self.gpu_status and self.gpu_status.cuda_available):
                logger.error(
                    f"Model {model.id}: vLLM requires CUDA GPU but none detected. "
                    "Marking UNAVAILABLE."
                )
                model.status = "UNAVAILABLE"
                return
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
                # Trigger fallback asynchronously so we don't block the health loop
                asyncio.create_task(self._activate_fallback(model.id))
                break
                
            await asyncio.sleep(5)
            
    async def _watch_startup_and_fallback(self):
        """
        After start_all(), waits up to 60 s for each auto-start model to reach READY.
        If any auto-start model is still UNAVAILABLE after that window, its fallback
        is activated automatically.
        """
        await asyncio.sleep(60)
        for model in self.registry.list_all():
            if model.auto_start and model.status == "UNAVAILABLE":
                logger.warning(
                    f"Auto-start model {model.id} never became READY within 60 s. "
                    "Triggering fallback."
                )
                asyncio.create_task(self._activate_fallback(model.id))

    async def _activate_fallback(self, failed_model_id: str):
        """
        Starts the configured fallback model for failed_model_id.
        Safe to call multiple times — deduped via _fallback_in_progress.
        """
        if failed_model_id in self._fallback_in_progress:
            return
        fallback = self.registry.get_fallback(failed_model_id)
        if not fallback:
            logger.warning(f"No fallback configured for {failed_model_id}. Service degraded.")
            return
        if fallback.status == "READY":
            logger.info(f"Fallback {fallback.id} is already READY.")
            return

        self._fallback_in_progress.add(failed_model_id)
        try:
            logger.warning(
                f"Primary model {failed_model_id} is UNAVAILABLE. "
                f"Activating fallback: {fallback.id}"
            )
            success = await self.start_model(fallback.id)
            if success:
                logger.info(f"Fallback {fallback.id} is now READY and serving requests.")
            else:
                logger.error(f"Fallback {fallback.id} also failed to start. No models available.")
        finally:
            self._fallback_in_progress.discard(failed_model_id)

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
            # Don't recurse into fallback here — caller (_activate_fallback) handles it
            return False
            
        await self._start_server(model)
        
        # Wait up to 60 seconds for the model to become READY
        for _ in range(60):
            if model.status == "READY":
                return True
            await asyncio.sleep(1)
            
        logger.warning(f"Timeout waiting for model {model_id} to become READY.")
        model.status = "UNAVAILABLE"
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
