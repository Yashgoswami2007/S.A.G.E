from typing import Any, Dict, Optional
from fastapi import status

class SAGEError(Exception):
    """Base exception for all SAGE runtime errors."""
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

class AuthError(SAGEError):
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHENTICATION_FAILED",
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details,
        )

class PermissionDeniedError(SAGEError):
    def __init__(self, message: str = "Permission denied", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="PERMISSION_DENIED",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )

class ResourceNotFoundError(SAGEError):
    def __init__(self, message: str = "Resource not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )

class ValidationError(SAGEError):
    def __init__(self, message: str = "Validation error", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )

class ModelError(SAGEError):
    def __init__(self, message: str, code: str = "MODEL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )

class CircuitBreakerOpenError(ModelError):
    def __init__(
        self,
        message: str = "Circuit breaker is OPEN",
        model_id: Optional[str] = None,
        recovery_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        info = details or {}
        if model_id:
            info["model_id"] = model_id
        if recovery_seconds is not None:
            info["recovery_seconds"] = recovery_seconds
        super().__init__(
            message=message,
            code="CIRCUIT_BREAKER_OPEN",
            details=info,
        )

class ToolError(SAGEError):
    def __init__(self, message: str, code: str = "TOOL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )

class ToolExecutionError(ToolError):
    def __init__(self, message: str, tool_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        info = details or {}
        if tool_name:
            info["tool_name"] = tool_name
        super().__init__(
            message=message,
            code="TOOL_EXECUTION_ERROR",
            details=info,
        )

class FileOperationError(ToolError):
    def __init__(self, message: str, path: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        info = details or {}
        if path:
            info["path"] = path
        super().__init__(
            message=message,
            code="FILE_OPERATION_ERROR",
            details=info,
        )

class SandboxError(SAGEError):
    def __init__(self, message: str, code: str = "SANDBOX_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )

class ConfigError(SAGEError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CONFIG_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )

class WorkspaceError(SAGEError):
    def __init__(self, message: str, code: str = "WORKSPACE_ERROR", status_code: int = status.HTTP_400_BAD_REQUEST, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )

class WorkspaceInvalidError(WorkspaceError):
    def __init__(self, message: str = "Invalid workspace path", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="WORKSPACE_INVALID",
            details=details,
        )

class WorkspaceNotFoundError(WorkspaceError):
    def __init__(self, message: str = "Workspace directory not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="WORKSPACE_NOT_FOUND",
            details=details,
        )

class WorkspaceForbiddenError(WorkspaceError):
    def __init__(self, message: str = "Path is a protected system directory", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="WORKSPACE_FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details,
        )

