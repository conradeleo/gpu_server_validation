"""Shared health status model used by collectors and (from Phase 4) the validation engine."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    """Ordered health model: HEALTHY < WARNING < DEGRADED < CRITICAL; UNKNOWN = no evidence."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        """Severity rank; UNKNOWN has no rank (-1) and is never the 'worst' known state."""
        return _RANK.get(self, -1)


_RANK = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.WARNING: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.CRITICAL: 3,
}

_REDFISH_HEALTH = {
    "ok": HealthStatus.HEALTHY,
    "warning": HealthStatus.WARNING,
    "critical": HealthStatus.CRITICAL,
}


def worst(statuses: Iterable[HealthStatus]) -> HealthStatus:
    """Worst *known* status; UNKNOWN only if nothing is known.

    Callers must report UNKNOWN members separately so they are not silently hidden.
    """
    known = [s for s in statuses if s is not HealthStatus.UNKNOWN]
    return max(known, key=lambda s: s.rank) if known else HealthStatus.UNKNOWN


def from_redfish_health(value: Any) -> HealthStatus:
    """Map a Redfish ``Status.Health`` / ``Severity`` value (OK/Warning/Critical) to HealthStatus."""
    if not isinstance(value, str):
        return HealthStatus.UNKNOWN
    return _REDFISH_HEALTH.get(value.strip().lower(), HealthStatus.UNKNOWN)
