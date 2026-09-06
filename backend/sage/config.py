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
    WORKSPACE_DIR: str = "./workspace"

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

    # Sandbox
    SANDBOX_RUNS_DIR: str = "./workspace/sandbox_runs"

    # File uploads
    UPLOAD_DIR: str = "./workspace/uploads"

    # OCR
    OCR_ENGINE: str = "tesseract"

    # Models — default is relative to project root, resolved below
    MODEL_REGISTRY_PATH: str = "config/model_registry.yaml"

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
        instance.SANDBOX_RUNS_DIR = resolve_dir(instance.SANDBOX_RUNS_DIR)
        instance.UPLOAD_DIR = resolve_dir(instance.UPLOAD_DIR)

        os.makedirs(instance.WORKSPACE_DIR, exist_ok=True)
        os.makedirs(instance.SANDBOX_RUNS_DIR, exist_ok=True)
        os.makedirs(instance.UPLOAD_DIR, exist_ok=True)

        path = instance.MODEL_REGISTRY_PATH
        if not os.path.isabs(path):
            abs_path = os.path.normpath(os.path.join(_PROJECT_ROOT, path))
            if os.path.exists(abs_path):
                instance.MODEL_REGISTRY_PATH = abs_path
        return instance

settings = Settings.load_from_yaml()
