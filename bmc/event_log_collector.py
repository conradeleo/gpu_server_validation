"""Event log collection, parsing and severity summary.

Redfish ``LogEntry`` objects are normalized into :class:`LogEvent`. Parsing is tolerant:
unknown severities and malformed timestamps are kept as UNKNOWN/None and listed as
anomalies rather than raising or being silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from bmc.redfish_client import RedfishClient
from common.status import HealthStatus, from_redfish_health, worst

logger = logging.getLogger(__name__)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp into an aware UTC datetime; ``None`` if invalid.

    Timestamps without an offset are assumed to be UTC.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class LogEvent:
    entry_id: str
    created: datetime | None
    severity: HealthStatus
    raw_severity: Any
    message_id: str | None
    message: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created": self.created.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created else None,
            "severity": self.severity.value,
            "raw_severity": self.raw_severity,
            "message_id": self.message_id,
            "message": self.message,
        }


def parse_log_entry(entry: dict[str, Any]) -> tuple[LogEvent, list[str]]:
    """Normalize one Redfish LogEntry; return the event and any parsing anomalies."""
    anomalies: list[str] = []
    eid = str(entry.get("Id", entry.get("@odata.id", "<no-id>")))
    created = parse_timestamp(entry.get("Created"))
    if created is None:
        anomalies.append(f"entry {eid}: invalid or missing Created {entry.get('Created')!r}")
    severity = from_redfish_health(entry.get("Severity"))
    if severity is HealthStatus.UNKNOWN:
        anomalies.append(f"entry {eid}: unrecognized Severity {entry.get('Severity')!r}")
    return (
        LogEvent(eid, created, severity, entry.get("Severity"), entry.get("MessageId"), entry.get("Message")),
        anomalies,
    )


@dataclass
class EventLogSummary:
    """Parsed events plus a severity roll-up.

    ``status`` is the worst known severity of events considered (after the ``since`` filter);
    HEALTHY when there are no considered events. Unknown severities do not escalate the status
    but are listed in ``anomalies``.
    """

    events: list[LogEvent]
    since: datetime | None = None
    anomalies: list[str] = field(default_factory=list)

    @property
    def considered(self) -> list[LogEvent]:
        if self.since is None:
            return self.events
        # Events with no valid timestamp cannot be proven old, so they are kept.
        return [e for e in self.events if e.created is None or e.created >= self.since]

    @property
    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for e in self.considered:
            c[e.severity.value] = c.get(e.severity.value, 0) + 1
        return c

    @property
    def status(self) -> HealthStatus:
        s = worst(e.severity for e in self.considered)
        return HealthStatus.HEALTHY if s is HealthStatus.UNKNOWN else s

    @property
    def latest_critical(self) -> LogEvent | None:
        crit = [e for e in self.considered if e.severity is HealthStatus.CRITICAL]
        return max(crit, key=lambda e: e.created or datetime.min.replace(tzinfo=timezone.utc), default=None)

    def as_dict(self) -> dict[str, Any]:
        lc = self.latest_critical
        return {
            "status": self.status.value,
            "total": len(self.events),
            "considered": len(self.considered),
            "since": self.since.strftime("%Y-%m-%dT%H:%M:%SZ") if self.since else None,
            "counts": self.counts,
            "latest_critical": lc.as_dict() if lc else None,
            "anomalies": self.anomalies,
        }


def summarize_entries(entries: list[dict[str, Any]], since: datetime | None = None) -> EventLogSummary:
    events: list[LogEvent] = []
    anomalies: list[str] = []
    for entry in entries:
        ev, notes = parse_log_entry(entry)
        events.append(ev)
        anomalies.extend(notes)
    for a in anomalies:
        logger.warning("Event log anomaly: %s", a)
    return EventLogSummary(events, since, anomalies)


def collect_event_log(client: RedfishClient, since: datetime | None = None) -> EventLogSummary:
    """Retrieve the system event log via the client and summarize it.

    Args:
        since: only events created at/after this aware datetime affect the status
            (e.g. the start of a validation run), so resolved historical events do not
            keep a server CRITICAL forever. All events are still returned.
    """
    if since is not None and since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    return summarize_entries(client.get_event_logs(), since)
