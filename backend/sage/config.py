from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import yaml
import os
import logging

_config_logger = logging.getLogger("sage.config")

# Absolute path to the directory that contains this file (backend/sage/)
# Used to anchor relative paths so they work regardless of where uvicorn is launched from.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Project root is two levels up: backend/sage/ -> backend/ -> project root
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))

class Settings(BaseSettings):
    # Base Config
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"
    AIRGAP_MODE: bool = False
    # Legacy shim: workspace manager overrides this at runtime, but serves as initial default
    WORKSPACE_DIR: str = "workspace"
    WORKSPACE_STATE_FILE: str = "config/workspace_state.json"

    # Database
    DATABASE_URL: str = Field(default="postgresql+asyncpg://sage:sage@localhost:5432/sage")
    REDIS_URL: str = Field(default="redis://localhost:6379")

    # JWT Auth
    JWT_SECRET: str = Field(default="dev_secret_key_change_me_in_prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 60
    
    # GPU — global override for GPU offloading mode
    # "auto" = use GPU if CUDA detected + VRAM sufficient, else CPU
    # "gpu"  = force GPU (fail if unavailable)
    # "cpu"  = force CPU-only
    GPU_MODE: str = "auto"
    
    # Model routing
    # False = never automatically switch/select specialized models.
    # The explicitly selected/default model remains in control.
    AUTO_MODEL_SWITCH: bool = False

    # Sandbox
    SANDBOX_RUNS_DIR: str = "./workspace/sandbox_runs"

    # File uploads
    UPLOAD_DIR: str = "./workspace/uploads"

    # OCR
    OCR_ENGINE: str = "tesseract"

    # Models — default is relative to project root, resolved below
    MODEL_REGISTRY_PATH: str = "config/model_registry.yaml"

    # Dynamic Tools
    DYNAMIC_TOOLS_ENABLED: bool = True
    DYNAMIC_TOOLS_MODEL: str = "auto"
    DYNAMIC_TOOLS_MAX_REPAIR_ATTEMPTS: int = 3
    DYNAMIC_TOOLS_DEFAULT_NETWORK: bool = False
    DYNAMIC_TOOLS_DEFAULT_SUBPROCESS: bool = False
    DYNAMIC_TOOLS_REQUIRE_APPROVAL_FOR_NETWORK: bool = True
    DYNAMIC_TOOLS_SANDBOX_TIMEOUT_SECONDS: int = 120  # Increased for RTX 5060 8GB (slower inference)
    DYNAMIC_TOOLS_PERSISTENCE_ENABLED: bool = True
    DYNAMIC_TOOLS_DEPENDENCIES_OFFLINE_ONLY: bool = True
    DYNAMIC_TOOLS_ALLOW_INSTALL: bool = False
    DYNAMIC_TOOLS_DIR: str = "./dynamic_tools"

    # Per-stage timeouts for Tool Factory pipeline (seconds)
    # LLM-bound stages need generous budgets on 8GB VRAM laptop GPUs
    TOOL_FACTORY_DESIGN_TIMEOUT: int = 600   # LLM call to produce ToolSpecification JSON
    TOOL_FACTORY_GENERATE_TIMEOUT: int = 600  # LLM call to generate Python code
    TOOL_FACTORY_VALIDATE_TIMEOUT: int = 300   # AST parsing + security policy check (fast, CPU-only)
    TOOL_FACTORY_TEST_TIMEOUT: int = 140     # Sandbox execution of generated code
    TOOL_FACTORY_OVERALL_MULTIPLIER: int = 60  # Overall budget = SANDBOX_TIMEOUT * this (720s @ 120s base)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def load_from_yaml(cls, yaml_path: str = "config/sage.yaml") -> "Settings":
        """Load settings from a YAML file, overridden by env vars."""
        # Resolve yaml_path relative to project root if it's not absolute
        if not os.path.isabs(yaml_path):
            yaml_path = os.path.join(_PROJECT_ROOT, yaml_path)
        if not os.path.exists(yaml_path):
            _config_logger.info(
                "Config file '%s' not found — using default settings.", yaml_path
            )
            instance = cls()
            instance = cls._resolve_paths(instance)
            return instance
        try:
            with open(yaml_path, "r") as f:
                yaml_config = yaml.safe_load(f) or {}
        except Exception as exc:
            _config_logger.warning(
                "Failed to read/parse config '%s': %s. Using default settings.",
                yaml_path, exc,
            )
            instance = cls()
            instance = cls._resolve_paths(instance)
            return instance
        # Strip Docker-style absolute paths that don't exist locally
        # so we fall through to the project-root-relative default
        registry_path = yaml_config.get("MODEL_REGISTRY_PATH", "")
        if registry_path and not os.path.exists(registry_path):
            yaml_config.pop("MODEL_REGISTRY_PATH", None)
        instance = cls(**yaml_config)
        return cls._resolve_paths(instance)

    @classmethod
    def _resolve_paths(cls, instance: "Settings") -> "Settings":
        """
        Resolve paths to absolute paths anchored at the project root.
        This makes it work regardless of the cwd when uvicorn is started.
        """
        def resolve_dir(path_str: str) -> str:
            if not os.path.isabs(path_str):
                return os.path.normpath(os.path.join(_PROJECT_ROOT, path_str))
            return os.path.normpath(path_str)

        instance.WORKSPACE_DIR = resolve_dir(instance.WORKSPACE_DIR)
        instance.WORKSPACE_STATE_FILE = resolve_dir(instance.WORKSPACE_STATE_FILE)
        instance.SANDBOX_RUNS_DIR = resolve_dir(instance.SANDBOX_RUNS_DIR)
        instance.UPLOAD_DIR = resolve_dir(instance.UPLOAD_DIR)

        os.makedirs(instance.WORKSPACE_DIR, exist_ok=True)
        os.makedirs(instance.SANDBOX_RUNS_DIR, exist_ok=True)
        os.makedirs(instance.UPLOAD_DIR, exist_ok=True)

        instance.DYNAMIC_TOOLS_DIR = resolve_dir(instance.DYNAMIC_TOOLS_DIR)
        os.makedirs(instance.DYNAMIC_TOOLS_DIR, exist_ok=True)

        path = instance.MODEL_REGISTRY_PATH
        if not os.path.isabs(path):
            abs_path = os.path.normpath(os.path.join(_PROJECT_ROOT, path))
            if os.path.exists(abs_path):
                instance.MODEL_REGISTRY_PATH = abs_path
        return instance

settings = Settings.load_from_yaml()
