"""Power-state collection and interpretation from the Redfish ComputerSystem resource."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bmc.redfish_client import RedfishClient

logger = logging.getLogger(__name__)


class PowerState(str, Enum):
    """Normalized power state. Values mirror Redfish ``PowerState`` plus UNKNOWN."""

    ON = "ON"
    OFF = "OFF"
    POWERING_ON = "POWERING_ON"
    POWERING_OFF = "POWERING_OFF"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


_REDFISH_MAP = {
    "on": PowerState.ON,
    "off": PowerState.OFF,
    "poweringon": PowerState.POWERING_ON,
    "poweringoff": PowerState.POWERING_OFF,
    "paused": PowerState.PAUSED,
}


def interpret_power_state(raw: Any) -> PowerState:
    """Map a raw Redfish ``PowerState`` value to :class:`PowerState`.

    Matching is case-insensitive (some BMCs deviate from the schema's casing).
    Missing, non-string or unrecognized values become ``UNKNOWN`` - never ``ON``.
    """
    if not isinstance(raw, str):
        return PowerState.UNKNOWN
    state = _REDFISH_MAP.get(raw.strip().lower(), PowerState.UNKNOWN)
    if state is PowerState.UNKNOWN:
        logger.warning("Unrecognized Redfish PowerState value: %r", raw)
    return state


@dataclass(frozen=True)
class PowerStateResult:
    """Raw and interpreted power state, kept together as test evidence."""

    raw_value: Any
    state: PowerState
    system_health: str | None
    source_uri: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_value": self.raw_value,
            "state": self.state.value,
            "system_health": self.system_health,
            "source_uri": self.source_uri,
        }


def collect_power_state(client: RedfishClient) -> PowerStateResult:
    """Read ``PowerState`` and ``Status.Health`` from the first ComputerSystem."""
    system = client.get_system()
    raw = system.get("PowerState")
    status = system.get("Status") if isinstance(system.get("Status"), dict) else {}
    return PowerStateResult(
        raw_value=raw,
        state=interpret_power_state(raw),
        system_health=status.get("Health"),
        source_uri=system.get("@odata.id", "<unknown>"),
    )
