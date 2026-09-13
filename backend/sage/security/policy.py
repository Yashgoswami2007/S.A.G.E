import os
from typing import List
from pydantic import BaseModel, Field
from sage.config import settings

class SecurityProfile(BaseModel):
    name: str
    allow_network: bool = False
    allow_subprocess: bool = False
    allow_filesystem_read: bool = False
    allow_filesystem_write: bool = False
    allowed_read_directories: List[str] = Field(default_factory=list)
    allowed_write_directories: List[str] = Field(default_factory=list)
    allowed_modules: List[str] = Field(default_factory=list)
    blocked_modules: List[str] = Field(default_factory=list)
    execution_timeout: int = 60

def get_safe_profile() -> SecurityProfile:
    import sage.workspace as _ws_module
    active = _ws_module.workspace_manager.get_active_workspace()
    return SecurityProfile(
        name="SAFE",
        allow_network=settings.DYNAMIC_TOOLS_DEFAULT_NETWORK,
        allow_subprocess=settings.DYNAMIC_TOOLS_DEFAULT_SUBPROCESS,
        allow_filesystem_read=True,
        allow_filesystem_write=True,
        allowed_read_directories=[active],
        allowed_write_directories=[active],
        allowed_modules=[
            "math", "json", "csv", "re", "datetime", "typing", "collections",
            "itertools", "functools", "urllib.parse", "uuid", "random", "hashlib",
            "base64", "io", "pathlib"
        ],
        blocked_modules=[
            "os", "sys", "subprocess", "socket", "ctypes", "importlib", "pickle", "shutil"
        ],
        execution_timeout=settings.DYNAMIC_TOOLS_SANDBOX_TIMEOUT_SECONDS
    )

class SecurityPolicy:
    @staticmethod
    def get_profile(name: str = "SAFE") -> SecurityProfile:
        # In the future, we could load from DB or config
        if name == "SAFE":
            return get_safe_profile()
        return get_safe_profile()
