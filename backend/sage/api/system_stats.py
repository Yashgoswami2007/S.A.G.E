import platform
import psutil
from fastapi import APIRouter
from sage.models.gpu_detector import detect_gpus, query_live_gpu_metrics

router = APIRouter()

# Cache the static CPU model string
_cpu_model = platform.processor()

@router.get("")
async def get_system_stats():
    """
    Returns live system telemetry for the frontend System Monitor.
    """
    # CPU
    cpu_percent = psutil.cpu_percent(interval=None) # Non-blocking since the second call
    cpu_cores = psutil.cpu_count(logical=False) or 0
    cpu_threads = psutil.cpu_count(logical=True) or 0
    
    # RAM
    mem = psutil.virtual_memory()
    
    # GPU
    gpu_data = {"available": False}
    static_gpus = detect_gpus()
    
    if static_gpus and static_gpus.cuda_available and static_gpus.gpus:
        # Just grab the first GPU for the compact monitor UI
        first_gpu = static_gpus.gpus[0]
        live_metrics = query_live_gpu_metrics()
        
        gpu_data = {
            "available": True,
            "name": first_gpu.name,
            "vram_total_mb": first_gpu.vram_total_mb,
            "utilization_percent": 0,
            "vram_used_mb": 0,
            "temperature_c": 0,
            "power_watts": 0.0
        }
        
        # Merge live metrics if we got them for the first GPU
        for live in live_metrics:
            if live["gpu_index"] == first_gpu.gpu_index:
                gpu_data.update({
                    "utilization_percent": live["utilization_percent"],
                    "vram_used_mb": live["vram_used_mb"],
                    "temperature_c": live["temperature_c"],
                    "power_watts": live["power_watts"],
                })
                break

    return {
        "cpu": {
            "usage_percent": cpu_percent,
            "core_count": cpu_cores,
            "thread_count": cpu_threads,
            "model": _cpu_model
        },
        "memory": {
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "usage_percent": mem.percent
        },
        "gpu": gpu_data
    }
