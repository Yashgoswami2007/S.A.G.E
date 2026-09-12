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
        Select the model for a request.
    
        When AUTO_MODEL_SWITCH is disabled, SAGE always uses the
        configured default model and does not automatically switch
        based on profile, vision, coding keywords, or attachments.
    
        When AUTO_MODEL_SWITCH is enabled, the existing automatic
        routing logic is used.
        """
        from sage.config import settings
    
        file_attachments = file_attachments or []
        prompt_lower = prompt.lower()
    
        # ============================================================
        # MANUAL MODEL MODE
        # ============================================================
        # User does not want SAGE to automatically switch models.
        # Always use the configured default model.
        if not settings.AUTO_MODEL_SWITCH:
            default_model = self.registry.get_default()
    
            if not default_model:
                all_models = self.registry.list_all()
    
                if all_models:
                    return (
                        all_models[0],
                        "automatic model switching disabled -> "
                        "using first registered model"
                    )
    
                raise RuntimeError(
                    "No models registered or available to route the request."
                )
    
            return (
                default_model,
                "automatic model switching disabled -> "
                "using configured default model"
            )
    
        # ============================================================
        # AUTOMATIC MODEL ROUTING
        # ============================================================
        # This section only runs when AUTO_MODEL_SWITCH=True.
    
        # 1. Profile Preference
        if profile_name == "coder":
            coder_model = self._get_best_for_capability("coding")
            if coder_model:
                reason = self._make_reason(
                    coder_model,
                    "coder profile requested -> selected coding model"
                )
                return coder_model, reason
    
        if profile_name == "inspector":
            vision_model = self._get_best_for_capability("vision")
            if vision_model:
                reason = self._make_reason(
                    vision_model,
                    "inspector profile requested -> selected vision model"
                )
                return vision_model, reason
    
        # 2. Input Modality Detection
        image_extensions = (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".bmp"
        )
    
        if (
            any(
                f.lower().endswith(image_extensions)
                for f in file_attachments
            )
            or "image" in prompt_lower
            or "photo" in prompt_lower
            or "diagram" in prompt_lower
        ):
            vision_model = self._get_best_for_capability("vision")
    
            if vision_model:
                reason = self._make_reason(
                    vision_model,
                    "image modality detected -> selected vision model"
                )
                return vision_model, reason
    
        # 3. Keyword / Heuristic Classification
        coding_keywords = [
            "code",
            "python",
            "function",
            "script",
            "refactor",
            "bug",
            "syntax",
            "patch",
            "class",
            "def "
        ]
    
        if any(
            kw in prompt_lower
            for kw in coding_keywords
        ):
            coder_model = self._get_best_for_capability("coding")
    
            if coder_model:
                reason = self._make_reason(
                    coder_model,
                    "coding keywords detected in prompt -> "
                    "selected coding model"
                )
                return coder_model, reason
    
        # 4. Fallback Default
        default_model = self.registry.get_default()
    
        if not default_model:
            all_ready = [
                m
                for m in self.registry.list_all()
                if m.status == "READY"
            ]
    
            if all_ready:
                all_ready.sort(key=lambda x: x.priority)
                return (
                    all_ready[0],
                    "fallback to first available ready model"
                )
    
            all_models = self.registry.list_all()
    
            if all_models:
                return (
                    all_models[0],
                    "fallback to first registered model "
                    "(none are marked READY)"
                )
    
            raise RuntimeError(
                "No models registered or available to route the request."
            )
    
        return (
            default_model,
            f"default profile '{profile_name or 'general'}' "
            "-> selected reasoning model"
        )
    def _get_best_for_capability(self, capability: str) -> Optional[ModelConfig]:
        """
        Returns the best model for a capability. Prefers READY models,
        but will return an UNAVAILABLE one if it exists (for swap-based loading).
        Respects AUTO_MODEL_SWITCH setting.
        """
        from sage.config import settings
        
        # First try to find a READY model
        ready_model = self.registry.get_ready_by_capability(capability)
        if ready_model:
            return ready_model
            
        if not settings.AUTO_MODEL_SWITCH:
            return None
        
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

