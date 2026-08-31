import yaml
import os
import structlog
from pydantic import BaseModel
from typing import List, Optional, Union

from sage.models.gpu_detector import HardwareProfile

# Project root: registry.py lives at backend/sage/models/registry.py
# so root is 3 levels up
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))

_logger = structlog.get_logger(__name__)

class ModelConfig(BaseModel):
    id: str
    name: str
    model_path: str
    server_port: int
    server_type: str = "llama-server"
    auto_start: bool = False
    gpu_layers: int = 99
    capabilities: List[str]
    priority: int
    min_vram_gb: int
    context_length: int
    status: str = "UNAVAILABLE"  # READY, DEGRADED, UNAVAILABLE
    fallback_model_id: Optional[str] = None  # id of model to try if this one fails

    # ── GPU acceleration fields ──────────────────────────────────────────
    # Controls how many layers to offload to GPU.
    #   "auto" — calculate optimal layer count based on available VRAM
    #   "all"  — offload everything (same as gpu_layers=99)
    #   "none" — force CPU-only (gpu_layers=0)
    #   int    — explicit layer count
    gpu_layers_policy: Union[str, int] = "auto"
    # Approximate model size in MB — used by "auto" policy for VRAM estimation.
    # If not set, falls back to min_vram_gb * 1024.
    estimated_size_mb: Optional[int] = None

    def resolve_gpu_layers(
        self,
        hardware: HardwareProfile,
        vram_reserve_mb: int = 512,
    ) -> int:
        """
        Resolve the final -ngl value based on the GPU policy and detected hardware.

        Args:
            hardware: Detected hardware profile from gpu_detector.
            vram_reserve_mb: VRAM (MB) to keep free for OS / other processes.

        Returns:
            Integer number of layers to offload to GPU.
        """
        policy = self.gpu_layers_policy

        # Explicit integer override
        if isinstance(policy, int):
            return max(policy, 0)

        # String policies
        policy_str = str(policy).lower().strip()

        if policy_str == "none":
            return 0

        if policy_str == "all":
            return self.gpu_layers  # Typically 99 → "offload everything"

        # "auto" — size layers based on available VRAM
        if policy_str == "auto":
            if hardware.selected_backend == "cpu" or hardware.selected_gpu is None:
                _logger.info(
                    "gpu_layers_policy=auto but no GPU available — using CPU",
                    model=self.id,
                )
                return 0

            available_mb = hardware.selected_gpu.vram_free_mb - vram_reserve_mb
            if available_mb <= 0:
                _logger.warning(
                    "Not enough free VRAM after reserve — falling back to CPU",
                    model=self.id,
                    vram_free_mb=hardware.selected_gpu.vram_free_mb,
                    reserve_mb=vram_reserve_mb,
                )
                return 0

            model_size_mb = self.estimated_size_mb or (self.min_vram_gb * 1024)
            if model_size_mb <= 0:
                return self.gpu_layers  # Can't estimate — offload all

            if available_mb >= model_size_mb:
                # Plenty of VRAM — offload everything
                _logger.info(
                    "Auto GPU layers: full offload",
                    model=self.id,
                    available_mb=available_mb,
                    model_size_mb=model_size_mb,
                )
                return self.gpu_layers  # 99 = all layers

            # Partial offload — estimate proportion of layers that fit
            ratio = available_mb / model_size_mb
            # Assume ~40 transformer layers for 7-8B models, ~60 for 12-13B
            estimated_total_layers = 60 if self.min_vram_gb >= 8 else 40
            partial_layers = max(1, int(estimated_total_layers * ratio))
            _logger.info(
                "Auto GPU layers: partial offload",
                model=self.id,
                available_mb=available_mb,
                model_size_mb=model_size_mb,
                ratio=round(ratio, 2),
                resolved_layers=partial_layers,
            )
            return partial_layers

        # Unknown policy — treat as int if parseable, else default to gpu_layers
        try:
            return max(int(policy_str), 0)
        except ValueError:
            _logger.warning(
                "Unrecognised gpu_layers_policy — defaulting to gpu_layers field",
                model=self.id,
                policy=policy,
            )
            return self.gpu_layers

class ModelRegistry:
    def __init__(self, registry_path: str):
        self.models: dict[str, ModelConfig] = {}
        self._load_registry(registry_path)
        
    def _load_registry(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            
        if data and "models" in data:
            for m in data["models"]:
                model_config = ModelConfig(**m)
                # Resolve relative model_path to absolute using project root
                # so llama-server can be launched from any working directory
                if not os.path.isabs(model_config.model_path):
                    model_config.model_path = os.path.normpath(
                        os.path.join(_PROJECT_ROOT, model_config.model_path)
                    )
                self.models[model_config.id] = model_config
                
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
