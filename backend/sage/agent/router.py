import re
from typing import Tuple, Optional, List
from sage.models.registry import ModelRegistry, ModelConfig

class ModelRouter:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def route(
        self,
        prompt: str,
        profile_name: Optional[str] = None,
        file_attachments: Optional[List[str]] = None
    ) -> Tuple[ModelConfig, str]:
        """
        Deterministically selects the optimal model for a given task.
        Returns (ModelConfig, routing_reason).
        
        Routing Logic Hierarchy:
        1. Explicit Profile Preference
        2. Input Modality Detection (Vision)
        3. Keyword & Heuristic Classification (Coding / Analysis)
        4. Reasoning Default Fallback
        """
        file_attachments = file_attachments or []
        prompt_lower = prompt.lower()

        # 1. Profile Preference
        if profile_name == "coder":
            coder_model = self.registry.get_by_capability("coding")
            if coder_model:
                return coder_model, "coder profile requested -> selected coding model"

        if profile_name == "inspector":
            vision_model = self.registry.get_by_capability("vision")
            if vision_model:
                return vision_model, "inspector profile requested -> selected vision model"

        # 2. Input Modality Detection
        image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        if any(f.lower().endswith(image_extensions) for f in file_attachments) or "image" in prompt_lower or "photo" in prompt_lower or "diagram" in prompt_lower:
            vision_model = self.registry.get_by_capability("vision")
            if vision_model:
                return vision_model, "image modality detected -> selected vision model"

        # 3. Keyword / Heuristic Classification
        coding_keywords = ["code", "python", "function", "script", "refactor", "bug", "syntax", "patch", "class", "def "]
        if any(kw in prompt_lower for kw in coding_keywords):
            coder_model = self.registry.get_by_capability("coding")
            if coder_model:
                return coder_model, "coding keywords detected in prompt -> selected coding model"

        # 4. Fallback Default
        default_model = self.registry.get_default()
        if not default_model:
            # Fallback to any model in registry
            all_models = self.registry.list_all()
            if all_models:
                return all_models[0], "fallback to first available model"
            # Hardcoded fallback config if registry empty
            return ModelConfig(
                id="qwen3-8b",
                name="Default Reasoning Model",
                model_path="/models/qwen3-8b-Q4_K_M.gguf",
                server_port=8001,
                capabilities=["reasoning"],
                priority=1,
                min_vram_gb=6,
                context_length=8192
            ), "fallback to hardcoded default reasoning model"

        return default_model, f"default profile '{profile_name or 'general'}' -> selected reasoning model"
