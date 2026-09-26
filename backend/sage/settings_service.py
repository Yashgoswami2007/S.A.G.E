"""
SAGE Settings Service — manages runtime + persistent configuration.

Provides a whitelist-based settings system that:
- Exposes only safe, user-configurable settings
- Validates types, ranges, and enum values
- Separates runtime application from YAML persistence
- Flags security-sensitive settings for confirmation
- Preserves YAML comments/formatting via ruamel.yaml
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from ruamel.yaml import YAML
from sage.config import settings, _PROJECT_ROOT

logger = logging.getLogger("sage.settings_service")

# ── Settings Schema ──────────────────────────────────────────────────────────
# Each entry defines a user-configurable setting with metadata.
# Only settings listed here are exposed via the API.

SETTINGS_SCHEMA: List[Dict[str, Any]] = [
    # ── General ──────────────────────────────────────────────────────────
    {
        "key": "ENVIRONMENT",
        "section": "general",
        "section_label": "General",
        "label": "Environment",
        "description": "Deployment environment. Affects logging defaults and debug behavior.",
        "type": "enum",
        "control": "select",
        "default": "dev",
        "options": ["dev", "staging", "prod"],
        "runtime": False,
        "persist": True,
        "restart_required": True,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    {
        "key": "LOG_LEVEL",
        "section": "general",
        "section_label": "General",
        "label": "Log Level",
        "description": "Controls backend logging verbosity. DEBUG produces very detailed output.",
        "type": "enum",
        "control": "select",
        "default": "INFO",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    {
        "key": "AIRGAP_MODE",
        "section": "general",
        "section_label": "General",
        "label": "Air-Gap Mode",
        "description": "When enabled, SAGE operates in fully offline mode with no external network access.",
        "type": "bool",
        "control": "toggle",
        "default": False,
        "options": None,
        "runtime": False,
        "persist": True,
        "restart_required": True,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    {
        "key": "AUTO_MODEL_SWITCH",
        "section": "general",
        "section_label": "General",
        "label": "Automatic Model Switch",
        "description": "When enabled, the system will dynamically switch to specialized models based on the prompt content. Default is off.",
        "type": "bool",
        "control": "toggle",
        "default": False,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    # ── GPU / Performance ────────────────────────────────────────────────
    {
        "key": "GPU_MODE",
        "section": "gpu",
        "section_label": "GPU / Performance",
        "label": "GPU Mode",
        "description": "Controls GPU offloading. 'auto' detects CUDA and VRAM availability. 'gpu' forces GPU (fails if unavailable). 'cpu' forces CPU-only.",
        "type": "enum",
        "control": "select",
        "default": "auto",
        "options": ["auto", "gpu", "cpu"],
        "runtime": False,
        "persist": True,
        "restart_required": True,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    # ── OCR ──────────────────────────────────────────────────────────────
    {
        "key": "OCR_ENGINE",
        "section": "ocr",
        "section_label": "OCR",
        "label": "OCR Engine",
        "description": "Optical character recognition engine used for image text extraction.",
        "type": "enum",
        "control": "select",
        "default": "tesseract",
        "options": ["tesseract", "paddleocr"],
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    # ── RAG (Knowledge Base) ──────────────────────────────────────────────
    {
        "key": "RAG_AUTO_INDEX_UPLOADS",
        "section": "rag",
        "section_label": "Knowledge Base (RAG)",
        "label": "Auto-Index Uploads",
        "description": "Automatically process and index supported documents into the local knowledge base when uploaded to a chat.",
        "type": "bool",
        "control": "toggle",
        "default": True,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    # ── Tool Factory ─────────────────────────────────────────────────────
    {
        "key": "DYNAMIC_TOOLS_ENABLED",
        "section": "tool_factory",
        "section_label": "Tool Factory",
        "label": "Enable Dynamic Tools",
        "description": "Allows SAGE to dynamically generate and execute new tools at runtime.",
        "type": "bool",
        "control": "toggle",
        "default": True,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_MODEL",
        "section": "tool_factory",
        "section_label": "Tool Factory",
        "label": "Tool Generation Model",
        "description": "Model used for tool synthesis. 'auto' selects the best available model.",
        "type": "string",
        "control": "text",
        "default": "auto",
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS",
        "section": "tool_factory",
        "section_label": "Tool Factory",
        "label": "Max Repair Attempts",
        "description": "Maximum number of times the factory will attempt to repair a failing generated tool.",
        "type": "int",
        "control": "number",
        "default": 3,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 1,
        "max": 10,
    },
    {
        "key": "DYNAMIC_TOOLS_PERSISTENCE_ENABLED",
        "section": "tool_factory",
        "section_label": "Tool Factory",
        "label": "Persist Generated Tools",
        "description": "When enabled, successfully generated tools are saved to disk for reuse across sessions.",
        "type": "bool",
        "control": "toggle",
        "default": True,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
    # ── Tool Factory Timeouts ────────────────────────────────────────────
    {
        "key": "DYNAMIC_TOOLS_SANDBOX_TIMEOUT_SECONDS",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Sandbox Timeout",
        "description": "Maximum execution time (seconds) for sandbox-run tool code. Increase for slower hardware.",
        "type": "int",
        "control": "number",
        "default": 120,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 10,
        "max": 600,
    },
    {
        "key": "TOOL_FACTORY_DESIGN_TIMEOUT",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Design Stage Timeout",
        "description": "Timeout (seconds) for the LLM call that produces a ToolSpecification. Increase for slower GPUs.",
        "type": "int",
        "control": "number",
        "default": 600,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 30,
        "max": 1800,
    },
    {
        "key": "TOOL_FACTORY_GENERATE_TIMEOUT",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Generate Stage Timeout",
        "description": "Timeout (seconds) for the LLM call that generates Python code. Increase for slower GPUs.",
        "type": "int",
        "control": "number",
        "default": 600,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 30,
        "max": 1800,
    },
    {
        "key": "TOOL_FACTORY_VALIDATE_TIMEOUT",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Validate Stage Timeout",
        "description": "Timeout (seconds) for AST parsing and security policy checks (CPU-only, fast).",
        "type": "int",
        "control": "number",
        "default": 300,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 10,
        "max": 600,
    },
    {
        "key": "TOOL_FACTORY_TEST_TIMEOUT",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Test Stage Timeout",
        "description": "Timeout (seconds) for sandbox execution of the generated tool code.",
        "type": "int",
        "control": "number",
        "default": 140,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 10,
        "max": 600,
    },
    {
        "key": "TOOL_FACTORY_OVERALL_MULTIPLIER",
        "section": "tool_factory_timeouts",
        "section_label": "Tool Factory Timeouts",
        "label": "Overall Timeout Multiplier",
        "description": "Overall budget = sandbox timeout × this value. Controls the total time allowed for a full tool synthesis pipeline.",
        "type": "int",
        "control": "number",
        "default": 60,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 1,
        "max": 120,
    },
    # ── Tool Security ────────────────────────────────────────────────────
    {
        "key": "DYNAMIC_TOOLS_DEFAULT_NETWORK",
        "section": "tool_security",
        "section_label": "Tool Security",
        "label": "Allow Network Access",
        "description": "When enabled, dynamically generated tools are allowed to make outbound network requests by default.",
        "type": "bool",
        "control": "toggle",
        "default": False,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": True,
        "requires_confirmation": True,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_DEFAULT_SUBPROCESS",
        "section": "tool_security",
        "section_label": "Tool Security",
        "label": "Allow Subprocess Execution",
        "description": "When enabled, dynamically generated tools can spawn subprocesses. This significantly reduces sandbox isolation.",
        "type": "bool",
        "control": "toggle",
        "default": False,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": True,
        "requires_confirmation": True,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_REQUIRE_APPROVAL_FOR_NETWORK",
        "section": "tool_security",
        "section_label": "Tool Security",
        "label": "Require Approval for Network",
        "description": "When enabled, tools requesting network access must be explicitly approved before execution.",
        "type": "bool",
        "control": "toggle",
        "default": True,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": True,
        "requires_confirmation": True,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_DEPENDENCIES_OFFLINE_ONLY",
        "section": "tool_security",
        "section_label": "Tool Security",
        "label": "Offline-Only Dependencies",
        "description": "When enabled, generated tools can only use pre-installed packages. Disabling allows downloading from the internet.",
        "type": "bool",
        "control": "toggle",
        "default": True,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": True,
        "requires_confirmation": True,
        "min": None,
        "max": None,
    },
    {
        "key": "DYNAMIC_TOOLS_ALLOW_INSTALL",
        "section": "tool_security",
        "section_label": "Tool Security",
        "label": "Allow Package Installation",
        "description": "When enabled, SAGE may install Python packages during tool synthesis. This grants significant system access.",
        "type": "bool",
        "control": "toggle",
        "default": False,
        "options": None,
        "runtime": True,
        "persist": True,
        "restart_required": False,
        "security_sensitive": True,
        "requires_confirmation": True,
        "min": None,
        "max": None,
    },
    # ── Server ───────────────────────────────────────────────────────────
    {
        "key": "JWT_EXPIRY_MINUTES",
        "section": "server",
        "section_label": "Server",
        "label": "JWT Token Expiry",
        "description": "Minutes until an authentication token expires. Changing this affects new tokens only.",
        "type": "int",
        "control": "number",
        "default": 60,
        "options": None,
        "runtime": False,
        "persist": True,
        "restart_required": True,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": 5,
        "max": 1440,
    },
    {
        "key": "JWT_ALGORITHM",
        "section": "server",
        "section_label": "Server",
        "label": "JWT Algorithm",
        "description": "Algorithm used for signing authentication tokens. Changing invalidates existing tokens.",
        "type": "enum",
        "control": "select",
        "default": "HS256",
        "options": ["HS256", "HS384", "HS512"],
        "runtime": False,
        "persist": True,
        "restart_required": True,
        "security_sensitive": False,
        "requires_confirmation": False,
        "min": None,
        "max": None,
    },
]

# Build a lookup for quick access
_SCHEMA_BY_KEY: Dict[str, Dict[str, Any]] = {s["key"]: s for s in SETTINGS_SCHEMA}

# Ordered section IDs for consistent UI rendering
_SECTION_ORDER = [
    "general",
    "gpu",
    "ocr",
    "tool_factory",
    "tool_factory_timeouts",
    "tool_security",
    "server",
]


def _is_less_secure(key: str, new_value: Any) -> bool:
    """Check if a change moves a security-sensitive setting toward a less-secure state."""
    schema = _SCHEMA_BY_KEY.get(key)
    if not schema or not schema.get("security_sensitive"):
        return False
    default = schema["default"]
    # For booleans: moving away from default is less secure
    # The defaults are designed to be the secure option
    return new_value != default


# ── Public API ───────────────────────────────────────────────────────────────


def get_settings() -> Dict[str, Any]:
    """
    Return all exposed settings grouped by section with current values and metadata.
    """
    sections: Dict[str, Dict[str, Any]] = {}

    for schema in SETTINGS_SCHEMA:
        section_id = schema["section"]
        if section_id not in sections:
            sections[section_id] = {
                "id": section_id,
                "label": schema["section_label"],
                "security_sensitive": False,
                "settings": [],
            }

        current_value = getattr(settings, schema["key"], schema["default"])

        sections[section_id]["settings"].append({
            "key": schema["key"],
            "label": schema["label"],
            "description": schema["description"],
            "type": schema["type"],
            "control": schema["control"],
            "value": current_value,
            "default": schema["default"],
            "options": schema["options"],
            "runtime": schema["runtime"],
            "persist": schema["persist"],
            "restart_required": schema["restart_required"],
            "security_sensitive": schema["security_sensitive"],
            "requires_confirmation": schema["requires_confirmation"],
            "min": schema["min"],
            "max": schema["max"],
        })

        if schema["security_sensitive"]:
            sections[section_id]["security_sensitive"] = True

    # Return ordered sections
    ordered = []
    for sid in _SECTION_ORDER:
        if sid in sections:
            ordered.append(sections[sid])
    # Append any sections not in the order list
    for sid, sec in sections.items():
        if sid not in _SECTION_ORDER:
            ordered.append(sec)

    return {"sections": ordered}


def get_defaults() -> Dict[str, Any]:
    """Return default values for all exposed settings."""
    return {schema["key"]: schema["default"] for schema in SETTINGS_SCHEMA}


def validate_setting(key: str, value: Any) -> Optional[str]:
    """
    Validate a single setting value against its schema.
    Returns an error message string, or None if valid.
    """
    schema = _SCHEMA_BY_KEY.get(key)
    if schema is None:
        return f"Unknown or non-configurable setting: '{key}'"

    expected_type = schema["type"]

    # Type validation
    if expected_type == "bool":
        if not isinstance(value, bool):
            return f"'{key}' must be a boolean (true/false)"

    elif expected_type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"'{key}' must be an integer"
        if schema["min"] is not None and value < schema["min"]:
            return f"'{key}' must be at least {schema['min']}"
        if schema["max"] is not None and value > schema["max"]:
            return f"'{key}' must be at most {schema['max']}"

    elif expected_type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"'{key}' must be a number"
        if schema["min"] is not None and value < schema["min"]:
            return f"'{key}' must be at least {schema['min']}"
        if schema["max"] is not None and value > schema["max"]:
            return f"'{key}' must be at most {schema['max']}"

    elif expected_type == "enum":
        if schema["options"] and value not in schema["options"]:
            return f"'{key}' must be one of: {', '.join(schema['options'])}"

    elif expected_type == "string":
        if not isinstance(value, str):
            return f"'{key}' must be a string"
        if len(value.strip()) == 0:
            return f"'{key}' cannot be empty"

    return None


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and apply setting changes.

    Returns:
        {
            "applied": [...],          # Keys applied at runtime
            "persisted": [...],        # Keys written to sage.yaml
            "restart_required": [...], # Keys that need restart to take effect
            "errors": {key: msg},      # Validation errors per key
            "security_confirmations": [...],  # Keys that were security-sensitive
            "settings": {...}          # Full refreshed settings state
        }
    """
    applied = []
    persisted = []
    restart_required = []
    errors = {}
    security_confirmations = []
    to_persist = {}

    # Phase 1: Validate all changes
    for key, value in changes.items():
        error = validate_setting(key, value)
        if error:
            errors[key] = error
            continue

    # If any validation errors, return early without applying anything
    if errors:
        return {
            "applied": [],
            "persisted": [],
            "restart_required": [],
            "errors": errors,
            "security_confirmations": [],
            "settings": get_settings(),
        }

    # Phase 2: Apply changes
    for key, value in changes.items():
        schema = _SCHEMA_BY_KEY[key]

        # Track security confirmations
        if schema["security_sensitive"] and _is_less_secure(key, value):
            security_confirmations.append(key)

        # Runtime application
        if schema["runtime"]:
            _apply_runtime(key, value)
            applied.append(key)
        elif schema["restart_required"]:
            restart_required.append(key)

        # Persistence
        if schema["persist"]:
            to_persist[key] = value
            persisted.append(key)

    # Phase 3: Persist to YAML
    if to_persist:
        _persist_to_yaml(to_persist)

    return {
        "applied": applied,
        "persisted": persisted,
        "restart_required": restart_required,
        "errors": errors,
        "security_confirmations": security_confirmations,
        "settings": get_settings(),
    }


def reset_settings(keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Reset specified settings (or all) to their defaults.
    Applies runtime changes and persists.
    """
    defaults = get_defaults()

    if keys is None:
        # Reset all
        target_keys = list(defaults.keys())
    else:
        target_keys = [k for k in keys if k in defaults]

    changes = {k: defaults[k] for k in target_keys}
    return update_settings(changes)


# ── Private helpers ──────────────────────────────────────────────────────────


def _apply_runtime(key: str, value: Any) -> None:
    """Mutate the global settings singleton for a runtime-safe setting."""
    setattr(settings, key, value)
    logger.info("Runtime setting updated: %s = %r", key, value)

    # Special case: LOG_LEVEL also needs to update Python logging
    if key == "LOG_LEVEL":
        log_level = getattr(logging, value.upper(), logging.INFO)
        logging.getLogger("sage").setLevel(log_level)
        logger.info("Python logger 'sage' level set to %s", value)


def _persist_to_yaml(changes: Dict[str, Any]) -> None:
    """
    Write changed settings to config/sage.yaml using ruamel.yaml
    for comment and formatting preservation.
    """
    yaml = YAML()
    yaml.preserve_quotes = True  # type: ignore[assignment]

    yaml_path = os.path.join(_PROJECT_ROOT, "config", "sage.yaml")

    # Load existing content (or start fresh)
    if os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            doc = yaml.load(f)
        if doc is None:
            doc = {}
    else:
        doc = {}

    # Merge changes
    for key, value in changes.items():
        doc[key] = value

    # Write back — ruamel.yaml preserves comments and formatting
    os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(doc, f)

    logger.info("Persisted %d setting(s) to %s", len(changes), yaml_path)
