"""
SAGE Settings API — GET / PATCH / POST reset endpoints.

All validation and application logic lives in settings_service.py.
This module only handles HTTP request/response mapping.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from sage.settings_service import get_settings, update_settings, reset_settings, validate_setting, _SCHEMA_BY_KEY

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    """Partial settings update — only changed keys."""
    changes: Dict[str, Any]


class SettingsResetRequest(BaseModel):
    """Reset specific keys or all settings to defaults."""
    keys: Optional[List[str]] = None
    all: bool = False


@router.get("")
async def get_all_settings():
    """
    Returns all user-configurable settings grouped by section,
    with current values, metadata, and schema information.
    """
    return get_settings()


@router.patch("")
async def patch_settings(body: SettingsUpdateRequest):
    """
    Apply partial settings changes.

    - Validates all values against the schema
    - Rejects unknown or hidden settings
    - Applies runtime-safe changes immediately
    - Persists all changes to config/sage.yaml
    - Returns which changes were applied, which need restart, and any errors
    """
    if not body.changes:
        raise HTTPException(status_code=400, detail="No changes provided")

    # Reject any keys not in the whitelist
    unknown_keys = [k for k in body.changes if k not in _SCHEMA_BY_KEY]
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or non-configurable settings: {', '.join(unknown_keys)}"
        )

    result = update_settings(body.changes)

    # If there were validation errors, return 422
    if result["errors"]:
        return {
            **result,
            "_status": "validation_error",
        }

    return {
        **result,
        "_status": "ok",
    }


@router.post("/reset")
async def reset_to_defaults(body: SettingsResetRequest):
    """
    Reset settings to their factory defaults.

    - If `all` is true, resets every exposed setting
    - If `keys` is provided, resets only those settings
    - Applies runtime changes and persists to YAML
    """
    if body.all:
        result = reset_settings(keys=None)
    elif body.keys:
        # Validate that all keys exist in the whitelist
        unknown = [k for k in body.keys if k not in _SCHEMA_BY_KEY]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown or non-configurable settings: {', '.join(unknown)}"
            )
        result = reset_settings(keys=body.keys)
    else:
        raise HTTPException(status_code=400, detail="Provide 'keys' or set 'all' to true")

    return result
