import yaml
import os
import logging
from pydantic import BaseModel
from typing import List, Optional

logger = logging.getLogger("sage.registry")

# Project root: registry.py lives at backend/sage/models/registry.py
# so root is 3 levels up
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))

class ModelConfig(BaseModel):
    id: str
    name: str
    model_path: str
    server_port: int
    server_type: str = "llama-server"
    auto_start: bool = False
    gpu_layers: int = 99
    gpu_mode: str = "auto"  # "auto" | "gpu" | "cpu"
    capabilities: List[str]
    priority: int
    min_vram_gb: int         # Total VRAM the model needs (GB); runtime checks free VRAM
    context_length: int
    status: str = "UNAVAILABLE"  # READY, DEGRADED, UNAVAILABLE
    fallback_model_id: Optional[str] = None  # id of model to try if this one fails
    pre_started: bool = False  # True = server already running externally; skip spawn, just health-check

class ModelRegistry:
    def __init__(self, registry_path: str):
        self.models: dict[str, ModelConfig] = {}
        self._load_registry(registry_path)
        
    def _load_registry(self, path: str):
        if not os.path.exists(path):
            logger.warning(
                "Model registry file not found at '%s'. "
                "Continuing with no registered models — the router will use its hardcoded fallback.",
                path,
            )
            return
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            logger.warning(
                "Failed to read/parse model registry '%s': %s. "
                "Continuing with no registered models — the router will use its hardcoded fallback.",
                path, exc,
            )
            return
            
        if not data or "models" not in data:
            logger.warning(
                "Model registry '%s' is empty or missing 'models' key. "
                "Continuing with no registered models.",
                path,
            )
            return

        for idx, m in enumerate(data["models"]):
            try:
                model_config = ModelConfig(**m)
                # Resolve relative model_path to absolute using project root
                # so llama-server can be launched from any working directory
                if not os.path.isabs(model_config.model_path):
                    model_config.model_path = os.path.normpath(
                        os.path.join(_PROJECT_ROOT, model_config.model_path)
                    )
                self.models[model_config.id] = model_config
            except Exception as exc:
                logger.warning(
                    "Skipping invalid model entry #%d in '%s': %s",
                    idx, path, exc,
                )
                
    def get_by_capability(self, capability: str) -> Optional[ModelConfig]:
        """Finds the highest priority model with the given capability (regardless of status)."""
        capable_models = [m for m in self.models.values() if capability in m.capabilities]
        if not capable_models:
            return None
        capable_models.sort(key=lambda x: x.priority)
        return capable_models[0]
        
    def get_ready_by_capability(self, capability: str) -> Optional[ModelConfig]:
        """Finds the highest priority READY model with the given capability."""
        capable_models = [m for m in self.models.values() if capability in m.capabilities and m.status == "READY"]
        if not capable_models:
            return None
        capable_models.sort(key=lambda x: x.priority)
        return capable_models[0]
        
    def get_default(self) -> Optional[ModelConfig]:
        """Returns the highest priority general/reasoning model that is READY."""
        return self.get_ready_by_capability("reasoning")

    def get_fallback(self, model_id: str) -> Optional[ModelConfig]:
        """
        Returns the configured fallback for the given model id, if any.
        The fallback does not need to be READY yet — the lifecycle manager
        will start it on demand.
        """
        model = self.models.get(model_id)
        if model and model.fallback_model_id:
            return self.models.get(model.fallback_model_id)
        return None
        
    def list_all(self) -> List[ModelConfig]:
        return list(self.models.values())
