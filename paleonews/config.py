from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file and .env."""
    load_dotenv()

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        return yaml.safe_load(f)
