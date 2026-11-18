"""Small helpers for locating and loading YAML configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Raised when a configuration file is missing or malformed."""


def resolve_path(path: str | Path) -> Path:
    """Resolve ``path`` relative to the project root unless it is absolute."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping from ``path``.

    Raises:
        ConfigError: if the file does not exist or does not contain a mapping.
    """
    p = resolve_path(path)
    if not p.is_file():
        raise ConfigError(f"Config file not found: {p}")
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {p} must contain a YAML mapping")
    return data


def load_test_config(path: str | Path = "config/test_config.yaml") -> dict[str, Any]:
    """Load the framework test configuration."""
    return load_yaml(path)
