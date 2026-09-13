from typing import List, Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field

class FilesystemPermissions(BaseModel):
    read: List[str] = Field(default_factory=list, description="List of allowed read directories (e.g., 'workspace')")
    write: List[str] = Field(default_factory=list, description="List of allowed write directories (e.g., 'artifacts')")

class PermissionRequest(BaseModel):
    filesystem: FilesystemPermissions = Field(default_factory=FilesystemPermissions)
    network: bool = Field(default=False, description="Whether network access is requested")
    subprocess: bool = Field(default=False, description="Whether subprocess execution is requested")

class RuntimeSpecification(BaseModel):
    language: str = Field(default="python", description="Language of the tool (e.g., python)")
    python_version: Optional[str] = Field(default="3.11")
    timeout_seconds: int = Field(default=60)

class ToolSpecification(BaseModel):
    name: str = Field(..., description="Machine-readable name of the tool (e.g., spreadsheet_generator)")
    description: str = Field(..., description="Human-readable description of what the tool does")
    capability: str = Field(..., description="The capability this tool fulfills (e.g., spreadsheet_generation)")
    version: str = Field(default="1.0.0", description="Semver version of the tool")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON Schema for input parameters")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON Schema for the output result")
    dependencies: List[str] = Field(default_factory=list, description="List of required package dependencies (e.g., openpyxl)")
    permissions: PermissionRequest = Field(default_factory=PermissionRequest, description="Requested permissions")
    runtime: RuntimeSpecification = Field(default_factory=RuntimeSpecification, description="Runtime execution specification")

class ToolProvenance(BaseModel):
    name: str
    version: str
    created_at: str
    created_for_capability: str
    generator_model: str
    source_task_id: str
    security_policy: str
    dependencies: List[str]
    validation_status: str = "pending"
    sandbox_status: str = "pending"

class ToolSynthesisState(str, Enum):
    DESIGNING = "DESIGNING"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    TESTING = "TESTING"
    REGISTERING = "REGISTERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class FactoryError(Exception):
    def __init__(self, stage: ToolSynthesisState, error_type: str, message: str, details: str, repairable: bool):
        self.stage = stage
        self.error_type = error_type
        self.message = message
        self.details = details
        self.repairable = repairable
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.stage}] {self.error_type}: {self.message}"
