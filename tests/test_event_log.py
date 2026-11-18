"""TC06 (event log retrieval and parsing) and supplementary event log tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bmc.event_log_collector import collect_event_log, parse_timestamp
from bmc.redfish_client import RedfishClient
from common.status import HealthStatus


@pytest.mark.tc(
    id="TC06",
    objective="Event logs can be retrieved and parsed.",
    preconditions=["Mock running", "Event log discovered via Systems -> LogServices -> EventLog -> Entries"],
    steps=["collect_event_log()", "Check entry count, IDs, UTC timestamps, severities, status"],
    expected="normal: 2 entries, all OK, HEALTHY; sensor_warning: 2 entries incl. 1 Warning, WARNING. "
             "All timestamps parsed as UTC; no anomalies.",
)
@pytest.mark.parametrize(
    ("scenario_name", "expected_counts", "expected_status"),
    [
        pytest.param("normal", {"HEALTHY": 2}, HealthStatus.HEALTHY, marks=pytest.mark.scenario("normal")),
        pytest.param("sensor_warning", {"HEALTHY": 1, "WARNING": 1}, HealthStatus.WARNING,
                     marks=pytest.mark.scenario("sensor_warning")),
    ],
)
def test_tc06_event_log_retrieved_and_parsed(
    redfish_client: RedfishClient, scenario_name, expected_counts, expected_status, evidence
) -> None:
    summary = collect_event_log(redfish_client)
    evidence.record(f"[{scenario_name}] {summary.as_dict()}", events=[e.as_dict() for e in summary.events])

    assert summary.counts == expected_counts
    assert summary.status is expected_status
    assert [e.entry_id for e in summary.events] == ["1", "2"]
    assert all(e.created is not None and e.created.tzinfo == timezone.utc for e in summary.events)
    assert all(e.message and e.message_id for e in summary.events)
    assert summary.anomalies == []


@pytest.mark.tc(
    id="SUP-EV-01",
    objective="A critical SEL event escalates the event log status to CRITICAL.",
    preconditions=["Mock scenario E (bmc_critical_host_failure)"],
    steps=["collect_event_log()", "Inspect status and latest_critical"],
    expected="Status CRITICAL; latest critical = entry 3 (GPU0 over-temperature) at 2026-11-18T10:05:42Z.",
)
@pytest.mark.scenario("bmc_critical_host_failure")
def test_critical_event(redfish_client: RedfishClient, evidence) -> None:
    summary = collect_event_log(redfish_client)
    lc = summary.latest_critical
    evidence.record(f"status={summary.status.value}, counts={summary.counts}, latest_critical={lc.as_dict() if lc else None}")
    assert summary.status is HealthStatus.CRITICAL
    assert lc is not None and lc.entry_id == "3" and "GPU0" in (lc.message or "")
    assert lc.created == datetime(2026, 11, 18, 10, 5, 42, tzinfo=timezone.utc)


@pytest.mark.tc(
    id="SUP-EV-02",
    objective="The 'since' window excludes events from before the validation run.",
    preconditions=["Mock scenario E; critical event at 10:05:42Z"],
    steps=["collect_event_log(since=10:03Z)", "collect_event_log(since=10:10Z)"],
    expected="since 10:03 -> CRITICAL (1 event considered); since 10:10 -> HEALTHY (0 considered), all 3 events still returned.",
)
@pytest.mark.scenario("bmc_critical_host_failure")
def test_since_window(redfish_client: RedfishClient, evidence) -> None:
    before = collect_event_log(redfish_client, since=datetime(2026, 11, 18, 10, 3, tzinfo=timezone.utc))
    after = collect_event_log(redfish_client, since=datetime(2026, 11, 18, 10, 10, tzinfo=timezone.utc))
    evidence.record(f"since 10:03 -> {before.status.value} ({len(before.considered)} considered); "
                    f"since 10:10 -> {after.status.value} ({len(after.considered)} considered, {len(after.events)} total)")
    assert before.status is HealthStatus.CRITICAL and len(before.considered) == 1
    assert after.status is HealthStatus.HEALTHY and after.considered == [] and len(after.events) == 3
    with pytest.raises(ValueError):
        collect_event_log(redfish_client, since=datetime(2026, 11, 18))


@pytest.mark.tc(
    id="SUP-EV-03",
    objective="Malformed event fields are tolerated and reported as anomalies.",
    preconditions=["Mock scenario sparse_sensors: invalid Created, naive timestamp, non-standard Severity"],
    steps=["collect_event_log()", "Inspect events and anomalies"],
    expected="No exception; entry 1 created=None; naive timestamp assumed UTC; 'Informational' -> UNKNOWN; "
             "2 anomalies listed; status HEALTHY (unknown severity does not escalate).",
)
@pytest.mark.scenario("sparse_sensors")
def test_malformed_event_fields(redfish_client: RedfishClient, evidence) -> None:
    summary = collect_event_log(redfish_client)
    evidence.record(f"{summary.as_dict()}")
    e1, e2 = summary.events
    assert e1.created is None
    assert e2.created == datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
    assert e2.severity is HealthStatus.UNKNOWN
    assert len(summary.anomalies) == 2
    assert summary.status is HealthStatus.HEALTHY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-18T10:30:00Z", datetime(2026, 11, 18, 10, 30, tzinfo=timezone.utc)),
        ("2026-11-18T18:30:00+08:00", datetime(2026, 11, 18, 10, 30, tzinfo=timezone.utc)),
        ("2026-11-18T10:30:00", datetime(2026, 11, 18, 10, 30, tzinfo=timezone.utc)),
        ("garbage", None),
        ("", None),
        (None, None),
    ],
)
@pytest.mark.tc(
    id="SUP-EV-04",
    objective="Timestamps are normalized to UTC (unit level).",
    preconditions=["None"],
    steps=["parse_timestamp()"],
    expected="Z / offset / naive inputs -> aware UTC; invalid -> None.",
)
def test_parse_timestamp(raw, expected, evidence) -> None:
    got = parse_timestamp(raw)
    evidence.record(f"{raw!r} -> {got}")
    assert got == expected
