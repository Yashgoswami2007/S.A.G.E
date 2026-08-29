import yaml
import os
from pydantic import BaseModel
from typing import List, Optional

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

class ModelRegistry:
    def __init__(self, registry_path: str):
        self.models: dict[str, ModelConfig] = {}
        self._load_registry(registry_path)
        
    def _load_registry(self, path: str):
        if not os.path.exists(path):
            # In a real environment we might want to log a warning here
            return
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            
        if data and "models" in data:
            for m in data["models"]:
                model_config = ModelConfig(**m)
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
        
    def list_all(self) -> List[ModelConfig]:
        return list(self.models.values())
