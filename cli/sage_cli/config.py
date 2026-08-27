import os
import yaml
from pathlib import Path
from pydantic import BaseModel

CONFIG_FILE = Path.home() / ".sage-cli.yaml"

class CLIConfig(BaseModel):
    backend_url: str = "http://localhost:8000"
    token: str | None = None
    workspace_dir: str = str(Path.cwd())

def load_config() -> CLIConfig:
    if not CONFIG_FILE.exists():
        return CLIConfig()
    try:
        with open(CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)
            return CLIConfig(**(data or {}))
    except Exception:
        return CLIConfig()

def save_config(config: CLIConfig):
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(config.model_dump(), f)

config = load_config()
