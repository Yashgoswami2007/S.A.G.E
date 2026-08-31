from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import yaml
import os

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

    # GPU Acceleration
    # "auto" — detect NVIDIA GPU automatically, fall back to CPU
    # "cuda" — force CUDA (error if no NVIDIA GPU)
    # "cpu"  — force CPU even if GPU is available
    GPU_BACKEND: str = "auto"
    # VRAM (MB) to keep free for OS / other processes when auto-sizing GPU layers
    GPU_MEMORY_RESERVE_MB: int = 512

    # Database
    DATABASE_URL: str = Field(default="postgresql+asyncpg://sage:sage@localhost:5432/sage")
    REDIS_URL: str = Field(default="redis://localhost:6379")

    # JWT Auth
    JWT_SECRET: str = Field(default="dev_secret_key_change_me_in_prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 60
    
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
            instance = cls()
            instance = cls._resolve_paths(instance)
            return instance
        with open(yaml_path, "r") as f:
            yaml_config = yaml.safe_load(f) or {}
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
        Resolve MODEL_REGISTRY_PATH to an absolute path anchored at the project root.
        This makes it work regardless of the cwd when uvicorn is started.
        """
        path = instance.MODEL_REGISTRY_PATH
        if not os.path.isabs(path):
            abs_path = os.path.join(_PROJECT_ROOT, path)
            if os.path.exists(abs_path):
                instance.MODEL_REGISTRY_PATH = abs_path
        return instance

settings = Settings.load_from_yaml()
