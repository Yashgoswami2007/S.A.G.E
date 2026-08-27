from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import yaml
import os

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
    
    # Models
    MODEL_REGISTRY_PATH: str = "config/model_registry.yaml"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def load_from_yaml(cls, yaml_path: str = "config/sage.yaml") -> "Settings":
        """Load settings from a YAML file, overridden by env vars."""
        if not os.path.exists(yaml_path):
            return cls()
        with open(yaml_path, "r") as f:
            yaml_config = yaml.safe_load(f) or {}
        return cls(**yaml_config)

settings = Settings.load_from_yaml()
