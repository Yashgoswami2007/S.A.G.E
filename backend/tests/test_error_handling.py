import pytest
from fastapi.testclient import TestClient
from sage.main import app
from sage.core.exceptions import (
    SAGEError,
    ResourceNotFoundError,
    ModelError,
    CircuitBreakerOpenError,
    FileOperationError,
    PermissionDeniedError,
)

client = TestClient(app)


def test_custom_sage_exceptions():
    """Verify SAGE domain exceptions carry structured attributes."""
    err = ResourceNotFoundError("Model weights not found", details={"model_id": "test-model"})
    assert err.code == "NOT_FOUND"
    assert err.status_code == 404
    assert err.message == "Model weights not found"
    assert err.details == {"model_id": "test-model"}

    cb_err = CircuitBreakerOpenError("Circuit open for model", details={"recovery_time_remaining_s": 25.4})
    assert cb_err.code == "CIRCUIT_BREAKER_OPEN"
    assert cb_err.status_code == 503
    assert cb_err.details["recovery_time_remaining_s"] == 25.4


def test_404_structured_envelope():
    """Verify non-existent routes return unified error response with detail backwards compatibility."""
    resp = client.get("/non-existent-route-for-testing")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "detail" in data
    assert data["detail"] == data["error"]["message"]


def test_validation_error_structured_envelope():
    """Verify validation failures return unified error envelope."""
    resp = client.post("/api/chat/completions", json={"invalid_field": 123})
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["status_code"] == 422
    assert "detail" in data


def test_admin_nonexistent_model_activation_error():
    """Verify activating a non-existent model returns 404 with structured error."""
    with TestClient(app) as tc:
        resp = tc.post("/api/admin/models/completely-invalid-model-xyz/activate")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"
        assert "completely-invalid-model-xyz" in data["error"]["message"]
