import copy
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


def apply_settings_overlay(config: dict, overrides: dict[str, str]) -> dict:
    """Return a new config with dot-path overrides applied on top.

    Example: {"summarizer.model": "claude-sonnet-4-6"} ->
        config["summarizer"]["model"] = "claude-sonnet-4-6"

    Values are stored as strings; callers needing booleans should coerce.
    """
    if not overrides:
        return config
    out = copy.deepcopy(config)
    for key, value in overrides.items():
        parts = key.split(".")
        d = out
        for p in parts[:-1]:
            if not isinstance(d.get(p), dict):
                d[p] = {}
            d = d[p]
        d[parts[-1]] = value
    return out
