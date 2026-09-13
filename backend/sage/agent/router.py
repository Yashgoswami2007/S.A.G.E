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
        
        VRAM-Swap Aware:
        If the ideal model is not READY (e.g., auto_start=false), the router
        still returns it with a "needs_swap" hint in the reason string. The 
        executor is responsible for triggering the lifecycle swap before calling.
        """
        file_attachments = file_attachments or []
        prompt_lower = prompt.lower()

        # 1. Profile Preference
        if profile_name == "coder":
            coder_model = self._get_best_for_capability("coding")
            if coder_model:
                reason = self._make_reason(coder_model, "coder profile requested -> selected coding model")
                return coder_model, reason

        if profile_name == "inspector":
            vision_model = self._get_best_for_capability("vision")
            if vision_model:
                reason = self._make_reason(vision_model, "inspector profile requested -> selected vision model")
                return vision_model, reason

        # 2. Input Modality Detection
        image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        if any(f.lower().endswith(image_extensions) for f in file_attachments) or "image" in prompt_lower or "photo" in prompt_lower or "diagram" in prompt_lower:
            vision_model = self._get_best_for_capability("vision")
            if vision_model:
                reason = self._make_reason(vision_model, "image modality detected -> selected vision model")
                return vision_model, reason

        # 3. Keyword / Heuristic Classification
        coding_keywords = ["code", "python", "function", "script", "refactor", "bug", "syntax", "patch", "class", "def "]
        if any(kw in prompt_lower for kw in coding_keywords):
            coder_model = self._get_best_for_capability("coding")
            if coder_model:
                reason = self._make_reason(coder_model, "coding keywords detected in prompt -> selected coding model")
                return coder_model, reason

        # 3b. Analysis / RAG Knowledge Keywords
        analysis_keywords = ["sop", "procedure", "manual", "compliance", "standard", "guideline", "threshold", "inspect"]
        if any(kw in prompt_lower for kw in analysis_keywords):
            reasoning_model = self._get_best_for_capability("reasoning")
            if reasoning_model:
                reason = self._make_reason(reasoning_model, "procedural/SOP keywords detected -> selected reasoning model")
                return reasoning_model, reason

        # 4. Fallback Default
        default_model = self.registry.get_default()
        if not default_model:
            # No READY reasoning model — check if any model is READY at all
            all_ready = [m for m in self.registry.list_all() if m.status == "READY"]
            if all_ready:
                all_ready.sort(key=lambda x: x.priority)
                return all_ready[0], "fallback to first available ready model"
            
            all_models = self.registry.list_all()
            if all_models:
                return all_models[0], "fallback to first registered model (none are marked READY)"
            return ModelConfig(
                id="qwen3-8b",
                name="Default Reasoning Model",
                model_path="/models/qwen3-8b-Q4_K_M.gguf",
                server_port=8001,
                capabilities=["reasoning"],
                priority=1,
                min_vram_gb=5,
                context_length=8192
            ), "fallback to hardcoded default reasoning model"

        return default_model, f"default profile '{profile_name or 'general'}' -> selected reasoning model"

    def _get_best_for_capability(self, capability: str) -> Optional[ModelConfig]:
        """
        Returns the best model for a capability. Prefers READY models,
        but will return an UNAVAILABLE one if it exists (for swap-based loading).
        """
        # First try to find a READY model
        ready_model = self.registry.get_ready_by_capability(capability)
        if ready_model:
            return ready_model
        
        # If no READY model, find any model with this capability (for swap)
        for model in self.registry.list_all():
            if capability in model.capabilities:
                return model
        return None

    def _make_reason(self, model: ModelConfig, base_reason: str) -> str:
        """Appends a swap hint if the model is not currently loaded."""
        if model.status != "READY":
            return f"{base_reason} [needs_swap]"
        return base_reason

