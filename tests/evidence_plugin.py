"""Pytest plugin that records structured test evidence.

Every test may carry ``@pytest.mark.tc(id=..., objective=..., preconditions=[...],
steps=[...], expected=...)`` and use the ``evidence`` fixture to record the actual
result. At session end the plugin writes ``reports/test_results.json``; it also adds
a "Test ID" column and an evidence block to the pytest-html report.

Result status: PASS / FAIL / WARNING (passed but ``evidence.warn()`` was called) / SKIPPED.
"""

from __future__ import annotations

import html
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

RESULTS_KEY = pytest.StashKey[list]()
EVIDENCE_ATTR = "_validation_evidence"


@dataclass
class Evidence:
    """Actual-result log for one test."""

    actual: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def record(self, message: str, **data: Any) -> None:
        """Record an observed fact (and optional structured data) as evidence."""
        self.actual.append(message)
        self.data.update(data)

    def warn(self, message: str) -> None:
        """Mark the test result as WARNING (test still passes)."""
        self.warnings.append(message)


@pytest.fixture
def evidence(request: pytest.FixtureRequest) -> Evidence:
    ev = Evidence()
    setattr(request.node, EVIDENCE_ATTR, ev)
    return ev


def pytest_configure(config: pytest.Config) -> None:
    config.stash[RESULTS_KEY] = []


def _tc_meta(item: pytest.Item) -> dict[str, Any]:
    marker = item.get_closest_marker("tc")
    return dict(marker.kwargs) if marker else {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):  # type: ignore[no-untyped-def]
    outcome = yield
    rep = outcome.get_result()
    meta = _tc_meta(item)
    rep.test_id = meta.get("id", "-")

    final = rep.when == "call" or (rep.when == "setup" and not rep.passed)
    if not final:
        return

    ev: Evidence = getattr(item, EVIDENCE_ATTR, Evidence())
    if rep.passed:
        status = "WARNING" if ev.warnings else "PASS"
    elif rep.skipped:
        status = "SKIPPED"
    else:
        status = "FAIL"

    actual = list(ev.actual)
    if rep.failed:
        last = (rep.longreprtext or "").strip().splitlines()
        actual.append(f"FAILURE ({rep.when}): {last[-1] if last else 'unknown error'}")

    scenario = item.get_closest_marker("scenario")
    record = {
        "test_id": rep.test_id,
        "nodeid": item.nodeid,
        "objective": meta.get("objective"),
        "preconditions": meta.get("preconditions", []),
        "steps": meta.get("steps", []),
        "expected": meta.get("expected"),
        "actual": actual,
        "warnings": ev.warnings,
        "data": ev.data,
        "scenario": scenario.args[0] if scenario else None,
        "status": status,
        "duration_s": round(rep.duration, 4),
    }
    item.config.stash[RESULTS_KEY].append(record)

    try:
        import pytest_html  # noqa: PLC0415

        block = "".join(
            f"<p><b>{html.escape(k)}:</b> {html.escape(str(v))}</p>"
            for k, v in (
                ("Test ID", record["test_id"]),
                ("Objective", record["objective"]),
                ("Expected", record["expected"]),
                ("Actual", " | ".join(actual)),
                ("Status", status),
            )
        )
        rep.extras = getattr(rep, "extras", []) + [pytest_html.extras.html(block)]
    except ImportError:
        pass


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_header(cells: list[str]) -> None:
    cells.insert(1, "<th>Test ID</th>")


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_row(report: pytest.TestReport, cells: list[str]) -> None:
    cells.insert(1, f"<td>{html.escape(getattr(report, 'test_id', '-'))}</td>")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    results: list[dict[str, Any]] = session.config.stash.get(RESULTS_KEY, [])
    summary: dict[str, int] = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    out = Path(session.config.rootpath) / "reports" / "test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "bmc_backend": "mock Redfish server (SIMULATED data)",
        },
        "exit_status": int(exitstatus),
        "summary": summary,
        "results": results,
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
