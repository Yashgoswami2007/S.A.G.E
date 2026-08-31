"""
Tests for ModelConfig.resolve_gpu_layers — VRAM-aware GPU layer resolution.
"""

import pytest
from sage.models.registry import ModelConfig
from sage.models.gpu_detector import GPUInfo, HardwareProfile


def _make_model(**overrides) -> ModelConfig:
    """Create a ModelConfig with sensible defaults for testing."""
    defaults = {
        "id": "test-model",
        "name": "Test Model",
        "model_path": "/models/test.gguf",
        "server_port": 8001,
        "capabilities": ["reasoning"],
        "priority": 1,
        "min_vram_gb": 5,
        "context_length": 8192,
        "gpu_layers": 99,
        "gpu_layers_policy": "auto",
        "estimated_size_mb": 5000,
    }
    defaults.update(overrides)
    return ModelConfig(**defaults)


def _make_hardware(backend: str = "cuda", vram_total: int = 16384, vram_free: int = 14200) -> HardwareProfile:
    """Create a HardwareProfile with a single GPU for testing."""
    if backend == "cpu":
        return HardwareProfile(selected_backend="cpu")

    gpu = GPUInfo(
        vendor="nvidia", backend="cuda", device_name="RTX 4060 Ti",
        vram_total_mb=vram_total, vram_free_mb=vram_free,
        driver_version="560.35", device_index=0,
    )
    return HardwareProfile(
        gpus=[gpu],
        selected_backend=backend,
        selected_gpu=gpu,
        total_vram_mb=vram_total,
    )


# ── Policy: "all" ──────────────────────────────────────────────────────────

class TestPolicyAll:

    def test_all_returns_gpu_layers(self):
        model = _make_model(gpu_layers_policy="all", gpu_layers=99)
        hw = _make_hardware()
        assert model.resolve_gpu_layers(hw) == 99

    def test_all_ignores_vram(self):
        model = _make_model(gpu_layers_policy="all", gpu_layers=99)
        hw = _make_hardware(vram_free=100)  # Almost no free VRAM
        # "all" means force offload everything — user takes responsibility
        assert model.resolve_gpu_layers(hw) == 99


# ── Policy: "none" ─────────────────────────────────────────────────────────

class TestPolicyNone:

    def test_none_returns_zero(self):
        model = _make_model(gpu_layers_policy="none")
        hw = _make_hardware(vram_free=16000)
        assert model.resolve_gpu_layers(hw) == 0


# ── Policy: explicit int ───────────────────────────────────────────────────

class TestPolicyExplicitInt:

    def test_integer_policy_returned_as_is(self):
        model = _make_model(gpu_layers_policy=32)
        hw = _make_hardware()
        assert model.resolve_gpu_layers(hw) == 32

    def test_negative_int_clamped_to_zero(self):
        model = _make_model(gpu_layers_policy=-5)
        hw = _make_hardware()
        assert model.resolve_gpu_layers(hw) == 0


# ── Policy: "auto" ─────────────────────────────────────────────────────────

class TestPolicyAuto:

    def test_auto_full_offload_when_plenty_of_vram(self):
        # Model needs 5 GB, 14 GB free — should offload all
        model = _make_model(gpu_layers_policy="auto", estimated_size_mb=5000, gpu_layers=99)
        hw = _make_hardware(vram_free=14200)
        result = model.resolve_gpu_layers(hw, vram_reserve_mb=512)
        assert result == 99  # Full offload

    def test_auto_partial_offload_when_tight_vram(self):
        # Model needs 5 GB, only 3 GB free after reserve → partial
        model = _make_model(
            gpu_layers_policy="auto", estimated_size_mb=5000,
            gpu_layers=99, min_vram_gb=5,
        )
        hw = _make_hardware(vram_free=3512)  # 3512 - 512 reserve = 3000 available
        result = model.resolve_gpu_layers(hw, vram_reserve_mb=512)
        # ratio = 3000/5000 = 0.6, estimated_layers=40 (min_vram_gb < 8), partial = 24
        assert 0 < result < 99
        assert result == 24

    def test_auto_zero_when_no_gpu(self):
        model = _make_model(gpu_layers_policy="auto")
        hw = _make_hardware(backend="cpu")
        assert model.resolve_gpu_layers(hw) == 0

    def test_auto_zero_when_no_vram_after_reserve(self):
        model = _make_model(gpu_layers_policy="auto", estimated_size_mb=5000)
        hw = _make_hardware(vram_free=400)  # Less than the 512 MB reserve
        assert model.resolve_gpu_layers(hw, vram_reserve_mb=512) == 0

    def test_auto_uses_min_vram_gb_fallback_when_no_estimated_size(self):
        # No estimated_size_mb → uses min_vram_gb * 1024
        model = _make_model(gpu_layers_policy="auto", estimated_size_mb=None, min_vram_gb=5)
        hw = _make_hardware(vram_free=14200)
        result = model.resolve_gpu_layers(hw, vram_reserve_mb=512)
        # 14200 - 512 = 13688, model_size = 5*1024=5120, 13688 >= 5120 → full offload
        assert result == 99

    def test_auto_large_model_uses_60_layers(self):
        # min_vram_gb >= 8 → 60 estimated layers
        model = _make_model(
            gpu_layers_policy="auto", estimated_size_mb=8000,
            min_vram_gb=8, gpu_layers=99,
        )
        hw = _make_hardware(vram_free=5512)  # 5512 - 512 = 5000 available
        result = model.resolve_gpu_layers(hw, vram_reserve_mb=512)
        # ratio = 5000/8000 = 0.625, estimated_layers=60, partial = 37
        assert result == 37


# ── Edge cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_string_integer_parsed(self):
        """A string like '25' in YAML should be parsed as 25 layers."""
        model = _make_model(gpu_layers_policy="25")
        hw = _make_hardware()
        assert model.resolve_gpu_layers(hw) == 25

    def test_unknown_policy_defaults_to_gpu_layers(self):
        model = _make_model(gpu_layers_policy="banana", gpu_layers=42)
        hw = _make_hardware()
        assert model.resolve_gpu_layers(hw) == 42
