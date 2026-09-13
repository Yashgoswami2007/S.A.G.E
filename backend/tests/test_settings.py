"""Tests for the SAGE Settings Service and API."""

import pytest
from unittest.mock import patch, MagicMock
from sage.settings_service import (
    get_settings,
    get_defaults,
    validate_setting,
    update_settings,
    reset_settings,
    _SCHEMA_BY_KEY,
    SETTINGS_SCHEMA,
)


class TestSettingsSchema:
    """Verify the schema structure is correct."""

    def test_all_settings_have_required_keys(self):
        required_keys = {
            "key", "section", "section_label", "label", "description",
            "type", "control", "default", "options", "runtime", "persist",
            "restart_required", "security_sensitive", "requires_confirmation",
            "min", "max",
        }
        for setting in SETTINGS_SCHEMA:
            missing = required_keys - set(setting.keys())
            assert not missing, f"Setting '{setting['key']}' missing keys: {missing}"

    def test_no_hidden_settings_exposed(self):
        """Ensure secrets and infrastructure paths are not in the schema."""
        hidden_keys = {
            "DATABASE_URL", "REDIS_URL", "JWT_SECRET",
            "WORKSPACE_DIR", "WORKSPACE_STATE_FILE",
            "SANDBOX_RUNS_DIR", "UPLOAD_DIR", "MODEL_REGISTRY_PATH",
            "DYNAMIC_TOOLS_DIR",
        }
        exposed_keys = {s["key"] for s in SETTINGS_SCHEMA}
        overlap = hidden_keys & exposed_keys
        assert not overlap, f"Security-sensitive settings exposed: {overlap}"

    def test_security_settings_require_confirmation(self):
        """All security_sensitive settings must require confirmation."""
        for setting in SETTINGS_SCHEMA:
            if setting["security_sensitive"]:
                assert setting["requires_confirmation"], (
                    f"Security-sensitive setting '{setting['key']}' should require confirmation"
                )


class TestValidation:
    """Test the validate_setting function."""

    def test_reject_unknown_key(self):
        err = validate_setting("NONEXISTENT_SETTING", "value")
        assert err is not None
        assert "Unknown" in err

    def test_reject_hidden_key(self):
        err = validate_setting("JWT_SECRET", "new_secret")
        assert err is not None

    def test_validate_bool(self):
        assert validate_setting("DYNAMIC_TOOLS_ENABLED", True) is None
        assert validate_setting("DYNAMIC_TOOLS_ENABLED", False) is None
        err = validate_setting("DYNAMIC_TOOLS_ENABLED", "yes")
        assert err is not None

    def test_validate_int_range(self):
        assert validate_setting("DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS", 3) is None
        err = validate_setting("DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS", 0)
        assert err is not None and "at least" in err
        err = validate_setting("DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS", 100)
        assert err is not None and "at most" in err

    def test_validate_enum(self):
        assert validate_setting("LOG_LEVEL", "DEBUG") is None
        err = validate_setting("LOG_LEVEL", "VERBOSE")
        assert err is not None and "must be one of" in err

    def test_validate_string(self):
        assert validate_setting("DYNAMIC_TOOLS_MODEL", "auto") is None
        err = validate_setting("DYNAMIC_TOOLS_MODEL", "  ")
        assert err is not None and "cannot be empty" in err

    def test_reject_bool_as_int(self):
        """bool is a subclass of int in Python — validate_setting should reject it."""
        err = validate_setting("DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS", True)
        assert err is not None


class TestGetSettings:
    """Test the get_settings function."""

    def test_returns_sections(self):
        result = get_settings()
        assert "sections" in result
        assert len(result["sections"]) > 0

    def test_sections_have_settings(self):
        result = get_settings()
        for section in result["sections"]:
            assert "id" in section
            assert "label" in section
            assert "settings" in section
            assert len(section["settings"]) > 0

    def test_each_setting_has_value(self):
        result = get_settings()
        for section in result["sections"]:
            for setting in section["settings"]:
                assert "key" in setting
                assert "value" in setting
                assert "default" in setting

    def test_security_section_flagged(self):
        result = get_settings()
        security_sections = [s for s in result["sections"] if s["security_sensitive"]]
        assert len(security_sections) > 0, "Should have at least one security-sensitive section"


class TestGetDefaults:
    """Test the get_defaults function."""

    def test_returns_all_exposed_keys(self):
        defaults = get_defaults()
        for setting in SETTINGS_SCHEMA:
            assert setting["key"] in defaults

    def test_defaults_match_schema(self):
        defaults = get_defaults()
        for setting in SETTINGS_SCHEMA:
            assert defaults[setting["key"]] == setting["default"]


class TestUpdateSettings:
    """Test the update_settings function."""

    def test_reject_invalid_values(self):
        result = update_settings({"LOG_LEVEL": "INVALID"})
        assert "LOG_LEVEL" in result["errors"]
        assert len(result["applied"]) == 0

    def test_runtime_setting_applied(self):
        from sage.config import settings
        original = settings.LOG_LEVEL
        try:
            result = update_settings({"DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS": 5})
            assert "DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS" in result["applied"]
            assert settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS == 5
        finally:
            settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS = 3

    def test_restart_required_flagged(self):
        # GPU_MODE is restart_required
        result = update_settings({"GPU_MODE": "cpu"})
        assert "GPU_MODE" in result["restart_required"]
        assert "GPU_MODE" not in result["applied"]

    def test_all_changes_rejected_on_any_error(self):
        """If any change is invalid, nothing should be applied."""
        from sage.config import settings
        original = settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS
        result = update_settings({
            "DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS": 5,
            "LOG_LEVEL": "INVALID",
        })
        assert len(result["errors"]) > 0
        assert len(result["applied"]) == 0
        assert settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS == original


class TestResetSettings:
    """Test the reset_settings function."""

    def test_reset_single_key(self):
        from sage.config import settings
        settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS = 7
        try:
            result = reset_settings(keys=["DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS"])
            assert settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS == 3
        finally:
            settings.DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS = 3
