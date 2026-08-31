"""
Tests for sage.models.gpu_detector — GPU hardware detection.

All tests mock subprocess calls so they run on any machine (including CI
without a GPU).
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from sage.models.gpu_detector import (
    GPUInfo,
    HardwareProfile,
    _detect_nvidia,
    detect_hardware,
    refresh_vram,
)


# ── nvidia-smi mock fixtures ────────────────────────────────────────────────

NVIDIA_SMI_OUTPUT_SINGLE = (
    "0, NVIDIA GeForce RTX 4060 Ti, 16384, 14200, 560.35.03\n"
)

NVIDIA_SMI_OUTPUT_MULTI = (
    "0, NVIDIA GeForce RTX 4060 Ti, 16384, 14200, 560.35.03\n"
    "1, NVIDIA GeForce RTX 3060, 12288, 11000, 560.35.03\n"
)


def _mock_run_nvidia(output: str, returncode: int = 0):
    """Create a mock subprocess.run result for nvidia-smi."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = output
    result.stderr = ""
    return result


# ── _detect_nvidia tests ────────────────────────────────────────────────────

class TestDetectNvidia:

    @patch("sage.models.gpu_detector.subprocess.run")
    def test_single_nvidia_gpu(self, mock_run):
        mock_run.return_value = _mock_run_nvidia(NVIDIA_SMI_OUTPUT_SINGLE)

        gpus = _detect_nvidia()

        assert len(gpus) == 1
        g = gpus[0]
        assert g.vendor == "nvidia"
        assert g.backend == "cuda"
        assert g.device_name == "NVIDIA GeForce RTX 4060 Ti"
        assert g.vram_total_mb == 16384
        assert g.vram_free_mb == 14200
        assert g.driver_version == "560.35.03"
        assert g.device_index == 0

    @patch("sage.models.gpu_detector.subprocess.run")
    def test_multi_nvidia_gpu(self, mock_run):
        mock_run.return_value = _mock_run_nvidia(NVIDIA_SMI_OUTPUT_MULTI)

        gpus = _detect_nvidia()

        assert len(gpus) == 2
        assert gpus[0].device_index == 0
        assert gpus[1].device_index == 1
        assert gpus[1].vram_total_mb == 12288

    @patch("sage.models.gpu_detector.subprocess.run", side_effect=FileNotFoundError)
    def test_nvidia_smi_not_found(self, mock_run):
        gpus = _detect_nvidia()
        assert gpus == []

    @patch("sage.models.gpu_detector.subprocess.run")
    def test_nvidia_smi_nonzero_exit(self, mock_run):
        mock_run.return_value = _mock_run_nvidia("", returncode=1)

        gpus = _detect_nvidia()
        assert gpus == []

    @patch("sage.models.gpu_detector.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10))
    def test_nvidia_smi_timeout(self, mock_run):
        gpus = _detect_nvidia()
        assert gpus == []

    @patch("sage.models.gpu_detector.subprocess.run")
    def test_nvidia_smi_malformed_csv(self, mock_run):
        mock_run.return_value = _mock_run_nvidia("garbage data\nmore garbage\n")

        gpus = _detect_nvidia()
        # Should not crash — just returns no valid GPUs
        assert gpus == []


# ── detect_hardware tests ───────────────────────────────────────────────────

class TestDetectHardware:

    @patch("sage.models.gpu_detector._detect_nvidia")
    def test_auto_with_nvidia(self, mock_nvidia):
        mock_nvidia.return_value = [
            GPUInfo(
                vendor="nvidia", backend="cuda",
                device_name="RTX 4060 Ti", vram_total_mb=16384,
                vram_free_mb=14200, driver_version="560.35", device_index=0
            )
        ]

        hw = detect_hardware(override_backend="auto")

        assert hw.selected_backend == "cuda"
        assert hw.selected_gpu is not None
        assert hw.selected_gpu.device_name == "RTX 4060 Ti"
        assert hw.total_vram_mb == 16384

    @patch("sage.models.gpu_detector._detect_nvidia", return_value=[])
    def test_auto_no_gpu(self, mock_nvidia):
        hw = detect_hardware(override_backend="auto")

        assert hw.selected_backend == "cpu"
        assert hw.selected_gpu is None
        assert hw.total_vram_mb == 0

    def test_force_cpu(self):
        hw = detect_hardware(override_backend="cpu")

        assert hw.selected_backend == "cpu"
        assert hw.selected_gpu is None
        assert hw.gpus == []

    @patch("sage.models.gpu_detector._detect_nvidia", return_value=[])
    def test_force_cuda_no_gpu_falls_back(self, mock_nvidia):
        hw = detect_hardware(override_backend="cuda")

        assert hw.selected_backend == "cpu"
        assert hw.detection_error is not None
        assert "no NVIDIA GPU" in hw.detection_error

    @patch("sage.models.gpu_detector._detect_nvidia")
    def test_selects_gpu_with_most_free_vram(self, mock_nvidia):
        mock_nvidia.return_value = [
            GPUInfo(vendor="nvidia", backend="cuda", device_name="RTX 3060",
                    vram_total_mb=12288, vram_free_mb=8000, driver_version="560", device_index=0),
            GPUInfo(vendor="nvidia", backend="cuda", device_name="RTX 4090",
                    vram_total_mb=24576, vram_free_mb=20000, driver_version="560", device_index=1),
        ]

        hw = detect_hardware(override_backend="auto")

        assert hw.selected_gpu.device_name == "RTX 4090"
        assert hw.selected_gpu.device_index == 1


# ── refresh_vram tests ──────────────────────────────────────────────────────

class TestRefreshVram:

    @patch("sage.models.gpu_detector.subprocess.run")
    def test_refresh_updates_free_vram(self, mock_run):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "12000\n"
        mock_run.return_value = result

        gpu = GPUInfo(
            vendor="nvidia", backend="cuda", device_name="RTX 4060",
            vram_total_mb=16384, vram_free_mb=14200, driver_version="560",
            device_index=0,
        )

        updated = refresh_vram(gpu)

        assert updated.vram_free_mb == 12000

    def test_refresh_noop_for_non_nvidia(self):
        gpu = GPUInfo(
            vendor="amd", backend="rocm", device_name="RX 7900",
            vram_total_mb=16384, vram_free_mb=14200, driver_version="6.0",
            device_index=0,
        )

        updated = refresh_vram(gpu)
        assert updated.vram_free_mb == 14200  # unchanged

    @patch("sage.models.gpu_detector.subprocess.run", side_effect=Exception("fail"))
    def test_refresh_handles_failure_gracefully(self, mock_run):
        gpu = GPUInfo(
            vendor="nvidia", backend="cuda", device_name="RTX 4060",
            vram_total_mb=16384, vram_free_mb=14200, driver_version="560",
            device_index=0,
        )

        updated = refresh_vram(gpu)
        assert updated.vram_free_mb == 14200  # unchanged on failure
