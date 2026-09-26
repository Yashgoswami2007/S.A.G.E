import asyncio
import os
import shutil
import httpx
import structlog
from typing import Dict, List, Optional
from sage.models.registry import ModelRegistry, ModelConfig
from sage.models.gpu_detector import detect_gpus, GPUStatus
from sage.models.model_scanner import ModelScanner

logger = structlog.get_logger(__name__)

# Resolve the llama-server binary path once at import time.
# Checks PATH first; if not found, falls back to the known Windows install location.
_LLAMA_SERVER_FALLBACK = r"C:\llama-cuda\llama-server.exe"

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
        self._model_ref_counts: Dict[str, int] = {}

        # GPU status — populated on start_all()
        self.gpu_status: Optional[GPUStatus] = None
        
    async def start_all(self):
        """Starts servers for all configured auto-start models if their GGUF files exist."""
        logger.info("Initializing Model Lifecycle Manager...")
        
        # ── Detect GPUs once at startup ───────────────────────────────────
        self.gpu_status = detect_gpus()
        self._log_gpu_banner()

        # ── Auto-discover models from /models/ directory ──────────────────
        self._scan_for_models()
        
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

        # Auto-start complete

    def _scan_for_models(self):
        """Auto-discover .gguf files in the models directory and merge into registry."""
        from sage.config import settings
        import os

        # Resolve models directory relative to project root
        _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
        _PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
        models_dir = os.path.join(_PROJECT_ROOT, "models")

        if not os.path.isdir(models_dir):
            logger.info(f"Models directory not found at {models_dir} — skipping auto-scan.")
            return

        scanner = ModelScanner(models_dir)
        existing_ids = self.registry.get_existing_ids()
        existing_ports = self.registry.get_existing_ports()
        discovered = scanner.scan(existing_ids, existing_ports)

        if discovered:
            added = self.registry.merge_discovered(discovered)
            logger.info(f"Auto-scan: merged {added} newly discovered model(s) into registry.")

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
            logger.info(f"Model {model.id}: gpu_mode=cpu -> ngl=0 (CPU-only)")
            return 0

        if effective_mode == "gpu":
            if not gpu_status.cuda_available:
                logger.error(
                    f"Model {model.id}: gpu_mode=gpu but no CUDA GPU detected - cannot start"
                )
                raise RuntimeError(f"gpu_mode=gpu requires CUDA but no GPU found for {model.id}")
            logger.info(f"Model {model.id}: gpu_mode=gpu -> ngl=99 (forced GPU offload)")
            return 99

        # effective_mode == "auto"
        if not gpu_status.cuda_available:
            logger.info(f"Model {model.id}: gpu_mode=auto, no CUDA -> ngl=0 (CPU fallback)")
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
                f"-> ngl=99 (GPU offload)"
            )
            return 99
        else:
            logger.warning(
                f"Model {model.id}: gpu_mode=auto, "
                f"needs {model.min_vram_gb} GB ({required_mb} MB) but only "
                f"{best_gpu.vram_free_mb} MB free on {best_gpu.name} "
                f"-> ngl=0 (CPU fallback - insufficient VRAM)"
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
            if model.is_embedding and "--embedding" not in (model.extra_args or []):
                cmd.append("--embedding")
                logger.info(f"Model {model.id}: embedding category, adding --embedding flag")
            # Append per-model extra args (e.g. --jinja for gemma-4)
            if model.extra_args:
                cmd.extend(model.extra_args)
                logger.info(f"Model {model.id}: appending extra_args: {model.extra_args}")
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
                break
                
            await asyncio.sleep(5)
            


    async def stop_all(self):
        """Terminates all running model servers."""
        logger.info("Shutting down model servers...")
        
        # Cancel health checks
        for task in self._health_tasks.values():
            task.cancel()
            
        # Terminate processes
        for model_id, proc in list(self._processes.items()):
            if proc.returncode is None:
                logger.info(f"Terminating server for {model_id}...")
                try:
                    proc.terminate()
                except Exception as term_err:
                    logger.debug(f"Process termination signal failed for {model_id}: {term_err}")
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"Force killing server for {model_id}...")
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception as kill_err:
                        logger.debug(f"Process kill failed for {model_id}: {kill_err}")
                except (RuntimeError, ProcessLookupError, Exception) as wait_err:
                    logger.debug(f"Process wait encountered for {model_id}: {wait_err}")
                    
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
            try:
                proc.terminate()
            except Exception as term_err:
                logger.debug(f"Process termination failed for {model_id}: {term_err}")
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as kill_err:
                    logger.debug(f"Process kill failed for {model_id}: {kill_err}")
            except (RuntimeError, ProcessLookupError, Exception) as wait_err:
                logger.debug(f"Process wait encountered for {model_id}: {wait_err}")
                
        model.status = "UNAVAILABLE"
        return True

    async def swap_model(self, load_id: str, unload_id: str) -> bool:
        """Swaps two models to manage VRAM."""
        logger.info(f"Swapping models: unloading {unload_id}, loading {load_id}")
        await self.stop_model(unload_id)
        # Add a short delay to ensure VRAM is cleared
        await asyncio.sleep(2)
        return await self.start_model(load_id)

    async def ensure_model(self, model_id: str) -> bool:
        """
        Ensure a model is loaded and READY.
        
        Called by RAG (for embedding) or any subsystem that needs a specific model.
        Unlike start_model(), this is ref-counted:
        - First call loads the model if not already running
        - Subsequent calls increment the ref count
        - The model stays loaded until release_model() decrements to 0
        
        If VRAM is insufficient, attempts to unload a lower-priority model
        (respecting category policy).
        
        Returns True if the model is READY.
        """
        model = self.registry.models.get(model_id)
        if not model:
            logger.error(f"ensure_model: {model_id} not in registry")
            return False
        
        # Increment ref count
        self._model_ref_counts[model_id] = self._model_ref_counts.get(model_id, 0) + 1
        
        # Already running?
        if model.status == "READY":
            return True
        
        # Need to load — check if we need to free VRAM first
        if not self._has_vram_for(model):
            candidate = self._pick_unload_candidate(model)
            if candidate:
                logger.info(
                    f"ensure_model: freeing VRAM by unloading {candidate.id} "
                    f"(category={candidate.model_category}) to load {model_id} "
                    f"(category={model.model_category})"
                )
                await self.stop_model(candidate.id)
                await asyncio.sleep(2)  # wait for VRAM release
        
        return await self.start_model(model_id)

    async def release_model(self, model_id: str):
        """
        Signal that a consumer no longer needs this model.
        
        Decrements ref count. When ref count reaches 0:
        - If VRAM is tight, the model becomes eligible for unloading
        - If VRAM is comfortable, the model stays resident (warm cache)
        
        Does NOT immediately unload — that decision is made by the swap
        logic when another model needs VRAM.
        """
        if model_id in self._model_ref_counts:
            self._model_ref_counts[model_id] = max(0, self._model_ref_counts[model_id] - 1)
            logger.debug(
                f"release_model: {model_id} ref_count now {self._model_ref_counts[model_id]}"
            )

    def _has_vram_for(self, model: ModelConfig) -> bool:
        """Check if current free VRAM can fit this model."""
        if not self.gpu_status or not self.gpu_status.cuda_available:
            return True  # CPU mode — always "fits"
        best_gpu = max(self.gpu_status.gpus, key=lambda g: g.vram_free_mb)
        required_mb = model.min_vram_gb * 1024
        return best_gpu.vram_free_mb >= required_mb

    def _pick_unload_candidate(self, requesting_model: ModelConfig) -> Optional[ModelConfig]:
        """
        Pick the best model to unload to make room for `requesting_model`.
        
        Policy (in priority order):
        1. Never unload a model that has ref_count > 0 (actively in use)
        2. Prefer unloading models of the SAME category as the requester
           (e.g., swap one chat model for another chat model)
        3. If no same-category candidate, prefer unloading lower-priority models
        4. Among equal candidates, prefer the one using more VRAM
        5. Never unload the requesting model itself
        """
        candidates = [
            m for m in self.registry.list_all()
            if m.status == "READY"
            and m.id != requesting_model.id
            and self._model_ref_counts.get(m.id, 0) == 0  # not actively in use
        ]
        
        if not candidates:
            return None
        
        # Sort: same-category first (to avoid cross-category disruption),
        # then by priority (higher number = lower importance), then by VRAM (larger first)
        def sort_key(m: ModelConfig):
            same_category = 0 if m.model_category == requesting_model.model_category else 1
            return (same_category, -m.priority, -m.min_vram_gb)
        
        candidates.sort(key=sort_key)
        return candidates[0]
