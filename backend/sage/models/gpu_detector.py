"""
GPU Detection Module — nvidia-smi based CUDA GPU detection for SAGE.

Uses `nvidia-smi --query-gpu=... --format=csv` as the sole authoritative
detector.  Result is cached for the process lifetime (hardware doesn't
change at runtime).
"""

import subprocess
import structlog
from typing import Optional
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


# ── Data Models ───────────────────────────────────────────────────────────────

class GPUInfo(BaseModel):
    """Information about a single NVIDIA GPU."""
    gpu_index: int          # Device ordinal (0, 1, …)
    name: str               # e.g. "NVIDIA GeForce RTX 3060"
    vram_total_mb: int      # Total VRAM in MB
    vram_free_mb: int       # Currently free VRAM in MB
    driver_version: str     # e.g. "560.35.03"
    cuda_version: str       # CUDA version reported by the driver, e.g. "12.4"


class GPUStatus(BaseModel):
    """Aggregate GPU status for the host machine."""
    cuda_available: bool    # True if at least one CUDA GPU was found
    gpu_count: int
    gpus: list[GPUInfo]
    driver_version: str     # Top-level convenience copy
    cuda_version: str       # Top-level convenience copy


# ── Detection ─────────────────────────────────────────────────────────────────

_cached_status: Optional[GPUStatus] = None


def _parse_nvidia_smi() -> Optional[GPUStatus]:
    """
    Run ``nvidia-smi`` and parse its CSV output.

    Query fields:
        index, name, memory.total, memory.free, driver_version, cuda_version

    Returns ``None`` when nvidia-smi is not installed, fails to execute,
    or produces unparseable output.
    """
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "nvidia-smi exited with non-zero code",
                returncode=result.returncode,
                stderr=result.stderr.strip(),
            )
            return None
    except FileNotFoundError:
        logger.info("nvidia-smi not found on PATH — no NVIDIA GPU detected")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("nvidia-smi timed out after 10 s")
        return None
    except Exception as exc:
        logger.warning("nvidia-smi failed unexpectedly", error=str(exc))
        return None

    # ── Grab driver & CUDA version from a separate lightweight query ──────
    driver_version = ""
    cuda_version = ""
    try:
        ver_result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if ver_result.returncode == 0 and ver_result.stdout.strip():
            # All GPUs share the same driver; take the first line.
            driver_version = ver_result.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    try:
        # nvidia-smi reports the highest CUDA version the driver supports
        # via the top-level header.  The quickest way to grab it is:
        header_result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=10,
        )
        if header_result.returncode == 0:
            for line in header_result.stdout.splitlines():
                if "CUDA Version:" in line:
                    # e.g. "| NVIDIA-SMI 560.35.03    Driver Version: 560.35.03    CUDA Version: 12.6  |"
                    cuda_version = line.split("CUDA Version:")[1].strip().rstrip("|").strip()
                    break
    except Exception:
        pass

    # ── Parse per-GPU CSV rows ────────────────────────────────────────────
    gpus: list[GPUInfo] = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            logger.warning("Skipping malformed nvidia-smi line", line=line)
            continue
        try:
            gpus.append(GPUInfo(
                gpu_index=int(parts[0]),
                name=parts[1],
                vram_total_mb=int(parts[2]),
                vram_free_mb=int(parts[3]),
                driver_version=driver_version,
                cuda_version=cuda_version,
            ))
        except (ValueError, IndexError) as exc:
            logger.warning("Failed to parse nvidia-smi row", line=line, error=str(exc))
            continue

    if not gpus:
        return None

    return GPUStatus(
        cuda_available=True,
        gpu_count=len(gpus),
        gpus=gpus,
        driver_version=driver_version,
        cuda_version=cuda_version,
    )


def detect_gpus(*, force_refresh: bool = False) -> GPUStatus:
    """
    Detect NVIDIA CUDA GPUs via nvidia-smi.

    Results are cached for the lifetime of the process.  Pass
    ``force_refresh=True`` to re-probe (useful in tests).
    """
    global _cached_status  # noqa: PLW0603

    if _cached_status is not None and not force_refresh:
        return _cached_status

    status = _parse_nvidia_smi()

    if status is None:
        status = GPUStatus(
            cuda_available=False,
            gpu_count=0,
            gpus=[],
            driver_version="",
            cuda_version="",
        )

    _cached_status = status

    if status.cuda_available:
        for gpu in status.gpus:
            logger.info(
                "CUDA GPU detected",
                index=gpu.gpu_index,
                name=gpu.name,
                vram_total_mb=gpu.vram_total_mb,
                vram_free_mb=gpu.vram_free_mb,
                driver=status.driver_version,
                cuda=status.cuda_version,
            )
    else:
        logger.info("No CUDA GPUs detected — models will run in CPU-only mode")

    return status


def query_live_gpu_metrics() -> list[dict]:
    """
    Query live GPU metrics (utilization, used VRAM, temperature, power).
    Returns a list of dicts, one per GPU.
    """
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,utilization.gpu,memory.used,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return []
        
        metrics = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                # Handle potential "Not Supported" values
                def parse_float(v):
                    try: return float(v)
                    except ValueError: return 0.0
                
                def parse_int(v):
                    try: return int(v)
                    except ValueError: return 0

                metrics.append({
                    "gpu_index": parse_int(parts[0]),
                    "utilization_percent": parse_int(parts[1]),
                    "vram_used_mb": parse_int(parts[2]),
                    "temperature_c": parse_int(parts[3]),
                    "power_watts": parse_float(parts[4]),
                })
        return metrics
    except Exception as exc:
        logger.debug("Failed to query live GPU metrics", error=str(exc))
        return []
