"""
GPU Hardware Detection Module for SAGE.

Detects NVIDIA GPUs via nvidia-smi, falls back to CPU when no compatible GPU
is found.  ROCm (AMD) detection is stubbed for future implementation.

Usage:
    from sage.models.gpu_detector import detect_hardware
    hw = detect_hardware()
    print(hw.selected_backend)  # "cuda" | "cpu"
"""

import subprocess
import csv
import io
import structlog
from dataclasses import dataclass, field
from typing import List, Optional

logger = structlog.get_logger(__name__)


@dataclass
class GPUInfo:
    """Represents a single detected GPU device."""
    vendor: str            # "nvidia" | "amd"
    backend: str           # "cuda" | "rocm"
    device_name: str       # e.g. "NVIDIA GeForce RTX 4060 Ti"
    vram_total_mb: int     # Total VRAM in MB
    vram_free_mb: int      # Free VRAM in MB
    driver_version: str    # e.g. "560.35.03"
    device_index: int      # GPU index (0-based)


@dataclass
class HardwareProfile:
    """Aggregated hardware detection result."""
    gpus: List[GPUInfo] = field(default_factory=list)
    selected_backend: str = "cpu"          # "cuda" | "rocm" | "cpu"
    selected_gpu: Optional[GPUInfo] = None
    total_vram_mb: int = 0
    detection_error: Optional[str] = None  # Non-fatal error message, if any


def _detect_nvidia() -> List[GPUInfo]:
    """
    Detect NVIDIA GPUs by calling nvidia-smi.

    Returns a list of GPUInfo for each detected NVIDIA device.
    Returns an empty list if nvidia-smi is not available or fails.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.debug("nvidia-smi returned non-zero exit code", returncode=result.returncode)
            return []

        gpus: List[GPUInfo] = []
        reader = csv.reader(io.StringIO(result.stdout.strip()))
        for row in reader:
            if len(row) < 5:
                continue
            # nvidia-smi CSV columns: index, name, memory.total [MiB], memory.free [MiB], driver_version
            try:
                idx = int(row[0].strip())
                name = row[1].strip()
                vram_total = int(float(row[2].strip()))
                vram_free = int(float(row[3].strip()))
                driver = row[4].strip()
                gpus.append(GPUInfo(
                    vendor="nvidia",
                    backend="cuda",
                    device_name=name,
                    vram_total_mb=vram_total,
                    vram_free_mb=vram_free,
                    driver_version=driver,
                    device_index=idx,
                ))
            except (ValueError, IndexError) as e:
                logger.warning("Failed to parse nvidia-smi row", row=row, error=str(e))
                continue

        return gpus

    except FileNotFoundError:
        logger.debug("nvidia-smi not found on PATH — no NVIDIA GPU detected")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("nvidia-smi timed out after 10 s")
        return []
    except Exception as e:
        logger.warning("Unexpected error running nvidia-smi", error=str(e))
        return []


def _detect_amd() -> List[GPUInfo]:
    """
    Stub for AMD ROCm GPU detection.

    ROCm support is planned for a future phase.  This function is here so the
    detection pipeline is already wired; it simply returns an empty list.
    """
    # TODO: Implement AMD ROCm detection via rocm-smi when ROCm support is added.
    #
    # Expected command:
    #   rocm-smi --showmeminfo vram --csv
    #
    # Parsing would follow the same pattern as _detect_nvidia().
    return []


def detect_hardware(override_backend: str = "auto") -> HardwareProfile:
    """
    Detect available GPU hardware and select the best inference backend.

    Args:
        override_backend: Force a specific backend.
            - "auto" — detect automatically (default)
            - "cuda" — force CUDA (fail if no NVIDIA GPU)
            - "cpu"  — force CPU even if a GPU is available

    Returns:
        HardwareProfile with detection results.
    """
    profile = HardwareProfile()

    # ── Forced CPU mode ──────────────────────────────────────────────────
    if override_backend == "cpu":
        logger.info("GPU backend override: forced CPU mode")
        profile.selected_backend = "cpu"
        return profile

    # ── Detect NVIDIA ────────────────────────────────────────────────────
    nvidia_gpus = _detect_nvidia()
    if nvidia_gpus:
        profile.gpus.extend(nvidia_gpus)
        # Select the GPU with the most free VRAM
        best = max(nvidia_gpus, key=lambda g: g.vram_free_mb)
        profile.selected_gpu = best
        profile.selected_backend = "cuda"
        profile.total_vram_mb = best.vram_total_mb
        logger.info(
            "NVIDIA GPU detected",
            device=best.device_name,
            vram_total_mb=best.vram_total_mb,
            vram_free_mb=best.vram_free_mb,
            driver=best.driver_version,
        )

        if override_backend == "cuda":
            return profile  # Caller explicitly wanted CUDA, and we found it
        return profile

    # ── Forced CUDA but no NVIDIA GPU ────────────────────────────────────
    if override_backend == "cuda":
        msg = "GPU_BACKEND=cuda but no NVIDIA GPU detected. Falling back to CPU."
        logger.warning(msg)
        profile.selected_backend = "cpu"
        profile.detection_error = msg
        return profile

    # ── Detect AMD (stub — returns empty for now) ────────────────────────
    amd_gpus = _detect_amd()
    if amd_gpus:
        profile.gpus.extend(amd_gpus)
        best = max(amd_gpus, key=lambda g: g.vram_free_mb)
        profile.selected_gpu = best
        profile.selected_backend = "rocm"
        profile.total_vram_mb = best.vram_total_mb
        logger.info("AMD GPU detected", device=best.device_name)
        return profile

    # ── No GPU found ─────────────────────────────────────────────────────
    logger.info("No compatible GPU detected — using CPU backend")
    profile.selected_backend = "cpu"
    return profile


def refresh_vram(gpu: GPUInfo) -> GPUInfo:
    """
    Re-query nvidia-smi for the latest free VRAM on a specific device.

    Useful before model loading to get an up-to-date VRAM snapshot.
    Returns the same GPUInfo with updated vram_free_mb, or the original
    if the query fails.
    """
    if gpu.vendor != "nvidia":
        return gpu

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--id={gpu.device_index}",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            free = int(float(result.stdout.strip()))
            gpu.vram_free_mb = free
    except Exception as e:
        logger.debug("Failed to refresh VRAM info", error=str(e))

    return gpu
