"""
SAGE Dynamic Model Scanner

Scans the models directory for .gguf files and infers metadata
(capabilities, display name, VRAM estimate) from filenames.
Models already defined in the YAML registry are skipped.
"""

import os
import re
import logging
from typing import List, Set

from sage.models.registry import ModelConfig

logger = logging.getLogger("sage.model_scanner")

# ── Capability inference patterns ──────────────────────────────────────────
# Each tuple: (list of substrings to match in lowercase filename, capabilities to assign)
_VISION_PATTERNS = [
    "gemma-4", "gemma4", "llava", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "minicpm-v", "pixtral", "internvl", "cogvlm", "phi-3-vision",
    "phi-3.5-vision", "moondream",
]

_CODING_PATTERNS = [
    "coder", "codellama", "deepseek-coder", "starcoder", "codestral",
    "qwen2.5-coder", "granite-code",
]

_EMBEDDING_PATTERNS = [
    "embed", "nomic-embed", "bge-", "gte-", "e5-", "minilm",
    "all-minilm", "instructor", "stella",
]

# Models known to need --jinja for proper chat templates
_JINJA_PATTERNS = [
    "gemma-4", "gemma4",
]

# Rough VRAM estimates based on quantization + param count in filename
_QUANT_VRAM_MAP = {
    "q2_k":   0.35,
    "q3_k_s": 0.40,
    "q3_k_m": 0.45,
    "q4_0":   0.50,
    "q4_k_s": 0.50,
    "q4_k_m": 0.55,
    "q5_0":   0.60,
    "q5_k_s": 0.60,
    "q5_k_m": 0.65,
    "q6_k":   0.75,
    "q8_0":   0.85,
    "f16":    2.00,
}


def _extract_param_billions(filename: str) -> float:
    """
    Try to extract parameter count from filename.
    e.g. 'Qwen3-8B-Q4_K_M.gguf' → 8.0
         'gemma-4-12b-it-Q4_K_M.gguf' → 12.0
         'phi-3.5-mini-3.8B-instruct-Q4_K_M.gguf' → 3.8
    """
    # Match patterns like 8B, 12b, 3.8B, 70B
    match = re.search(r'(\d+\.?\d*)[Bb]', filename)
    if match:
        return float(match.group(1))
    return 7.0  # default assumption


def _extract_quant(filename: str) -> str:
    """Extract quantization type from filename, e.g. 'Q4_K_M' → 'q4_k_m'."""
    match = re.search(r'(Q\d+_K(?:_[A-Z])?|Q\d+_\d|F16|F32)', filename, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return "q4_k_m"  # default assumption


def _estimate_vram_gb(filename: str) -> int:
    """Rough VRAM estimate: param_billions * quant_multiplier."""
    params = _extract_param_billions(filename)
    quant = _extract_quant(filename)
    multiplier = _QUANT_VRAM_MAP.get(quant, 0.55)
    vram = params * multiplier
    # Add ~0.5 GB overhead for KV cache at 8K context
    return max(1, int(vram + 0.5 + 0.5))


def _infer_capabilities(filename_lower: str) -> List[str]:
    """Infer model capabilities from the filename."""
    # Check embedding FIRST — embedding models should NOT get reasoning/general
    for pattern in _EMBEDDING_PATTERNS:
        if pattern in filename_lower:
            return ["embedding"]

    caps: Set[str] = {"reasoning", "general"}

    for pattern in _VISION_PATTERNS:
        if pattern in filename_lower:
            caps.add("vision")
            caps.add("coding")  # vision models are typically also good at coding
            break

    for pattern in _CODING_PATTERNS:
        if pattern in filename_lower:
            caps.add("coding")
            break

    return sorted(caps)


def _needs_jinja(filename_lower: str) -> bool:
    """Check if the model needs --jinja flag for proper chat templates."""
    return any(p in filename_lower for p in _JINJA_PATTERNS)


def _make_display_name(filename: str) -> str:
    """
    Generate a human-readable display name from a GGUF filename.
    'Qwen3-8B-Q4_K_M.gguf' → 'Qwen3 8B (Q4_K_M)'
    'gemma-4-12b-it-Q4_K_M.gguf' → 'Gemma 4 12B IT (Q4_K_M)'
    """
    stem = filename.rsplit(".", 1)[0]  # remove .gguf

    # Extract the quant part
    quant_match = re.search(r'(Q\d+_K(?:_[A-Z])?|Q\d+_\d|F16|F32)', stem, re.IGNORECASE)
    quant_str = quant_match.group(0) if quant_match else ""

    # Remove the quant part from the stem to get the model name
    name_part = stem
    if quant_str:
        name_part = name_part.replace(quant_str, "").strip("-_")

    # Clean up: replace hyphens/underscores with spaces, collapse whitespace
    name_part = name_part.replace("-", " ").replace("_", " ")
    name_part = re.sub(r'\s+', ' ', name_part).strip()

    # Title-case each word, but preserve known acronyms
    words = []
    for w in name_part.split():
        if w.upper() in ("IT", "VL", "DPO", "SFT", "GPTQ", "AWQ"):
            words.append(w.upper())
        elif re.match(r'^\d+[Bb]$', w):
            words.append(w.upper())
        else:
            words.append(w.capitalize())

    display = " ".join(words)
    if quant_str:
        display += f" ({quant_str})"

    return display


def _make_model_id(filename: str) -> str:
    """
    Generate a stable, URL-safe model ID from a filename.
    'Qwen3-8B-Q4_K_M.gguf' → 'qwen3-8b'
    'gemma-4-12b-it-Q4_K_M.gguf' → 'gemma-4-12b-it'
    """
    stem = filename.rsplit(".", 1)[0].lower()
    # Remove quant suffix
    stem = re.sub(r'[-_]?q\d+[-_]?k?(?:[-_]?[a-z])?$', '', stem)
    stem = re.sub(r'[-_]?f16$', '', stem)
    stem = re.sub(r'[-_]?f32$', '', stem)
    # Clean up trailing separators
    stem = stem.strip("-_")
    # Replace underscores with hyphens for consistency
    stem = stem.replace("_", "-")
    return stem


class ModelScanner:
    """
    Scans a directory for .gguf files and generates ModelConfig entries
    for any files not already registered in the YAML registry.
    """

    def __init__(self, models_dir: str, base_port: int = 8001):
        self.models_dir = os.path.abspath(models_dir)
        self.base_port = base_port

    def scan(self, existing_ids: Set[str], existing_ports: Set[int]) -> List[ModelConfig]:
        """
        Walk self.models_dir for *.gguf files.
        Skip any whose inferred ID matches an existing registry entry.
        Returns list of auto-discovered ModelConfig entries.
        """
        if not os.path.isdir(self.models_dir):
            logger.warning(f"Models directory not found: {self.models_dir}")
            return []

        discovered: List[ModelConfig] = []
        next_port = self.base_port

        # Find the next available port
        while next_port in existing_ports:
            next_port += 1

        for entry in sorted(os.listdir(self.models_dir)):
            if not entry.lower().endswith(".gguf"):
                continue

            file_path = os.path.join(self.models_dir, entry)
            if not os.path.isfile(file_path):
                continue

            model_id = _make_model_id(entry)

            # Check if this model (or a close variant) is already registered
            if model_id in existing_ids:
                logger.debug(f"Skipping already-registered model: {entry} (id={model_id})")
                continue

            # Also check by filename match — the YAML might use a different ID
            # but point to the same file
            already_by_path = any(
                os.path.basename(entry) in mid or mid in os.path.basename(entry).lower()
                for mid in existing_ids
            )
            if already_by_path:
                logger.debug(f"Skipping model with matching path: {entry}")
                continue

            filename_lower = entry.lower()
            capabilities = _infer_capabilities(filename_lower)
            extra_args = ["--jinja"] if _needs_jinja(filename_lower) else []
            if "embedding" in capabilities:
                extra_args.append("--embedding")
            vram_gb = _estimate_vram_gb(entry)
            display_name = _make_display_name(entry)

            # Find next free port
            while next_port in existing_ports:
                next_port += 1

            config = ModelConfig(
                id=model_id,
                name=display_name,
                model_path=file_path,
                server_port=next_port,
                server_type="llama-server",
                auto_start=False,  # auto-discovered models are on-demand only
                gpu_layers=99,
                gpu_mode="auto",
                capabilities=capabilities,
                priority=10,  # lower priority than YAML-defined models
                min_vram_gb=vram_gb,
                context_length=16384,
                extra_args=extra_args,
            )

            discovered.append(config)
            existing_ports.add(next_port)
            next_port += 1

            logger.info(
                f"Auto-discovered model: {model_id} "
                f"({display_name}, {capabilities}, ~{vram_gb}GB VRAM, port {config.server_port})"
            )

        if discovered:
            logger.info(f"Model scanner found {len(discovered)} new model(s) in {self.models_dir}")
        else:
            logger.info(f"Model scanner: no new models found in {self.models_dir}")

        return discovered