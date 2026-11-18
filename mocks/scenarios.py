"""Loading and merging of mock Redfish scenarios from YAML (all data is simulated)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from common.config import ConfigError, load_yaml

REQUIRED_KEYS = ("resource_ids", "system", "temperatures", "fans", "voltages", "events", "host")


def load_scenarios(path: str | Path) -> dict[str, dict[str, Any]]:
    """Return ``{name: merged_scenario}`` from a scenario file.

    Each scenario is shallow-merged over the file's ``defaults`` block.

    Raises:
        ConfigError: if the file has no scenarios or a merged scenario lacks required keys.
    """
    raw = load_yaml(path)
    defaults = raw.get("defaults") or {}
    scenarios = raw.get("scenarios") or {}
    if not isinstance(scenarios, dict) or not scenarios:
        raise ConfigError(f"No scenarios defined in {path}")

    merged: dict[str, dict[str, Any]] = {}
    for name, overrides in scenarios.items():
        data = copy.deepcopy(defaults)
        data.update(copy.deepcopy(overrides or {}))
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            raise ConfigError(f"Scenario '{name}' is missing keys: {missing}")
        data["name"] = name
        merged[name] = data
    return merged
