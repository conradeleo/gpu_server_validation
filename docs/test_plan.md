# Test Plan

## Objectives
Verify that the framework retrieves BMC data correctly over Redfish, interprets it safely, fails
predictably on BMC errors, and (later) aggregates BMC and host state into a correct system status.

## Scope
* **In scope (Milestone 1 + Phase 2):** Redfish service root, resource discovery, power state retrieval and
  interpretation, client error handling (auth, HTTP errors, unreachable BMC), secret hygiene,
  temperature/fan/voltage threshold classification, event-log parsing and severity summary,
  tolerance of incomplete BMC data.
* **Planned:** host collectors, aggregation, events, pool simulation.
* **Out of scope:** write/destructive BMC actions (power control, firmware update), real-hardware
  performance claims.

## Test environment
| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS |
| Python | 3.13.18 (venv in project) |
| BMC | In-process mock Redfish server (uvicorn on random loopback port), SIMULATED data |
| Credentials | Random per test session; never written to disk |
| Network | Loopback only; tests run offline |

## Strategy
* Unit tests for pure interpretation logic (parametrized, including invalid inputs).
* Integration tests of the real client against the mock over real HTTP.
* Scenario-driven: each test declares `@pytest.mark.scenario(...)`; an autouse fixture resets the
  scenario and clears injected faults before every test (no ordering dependencies).
* Negative tests via fault injection (`/mock/fault`), wrong credentials, closed ports.
* Evidence: every test declares ID/objective/preconditions/steps/expected via `@pytest.mark.tc`
  and records actual results; reports in JSON, HTML and JUnit XML.
* Regression: full suite on every change (TC12 will formalize this).

## Entry criteria
Dependencies installed from `requirements.txt`; scenario file loads; mock starts.

## Exit criteria
All implemented test cases PASS; no unexpected warnings; reports generated; docs updated with the
actual results of that run.

## Risks
| Risk | Mitigation |
|---|---|
| Mock diverges from real BMC behavior | Follow DMTF schemas; document simplifications; add OpenBMC-in-QEMU target later |
| Vendor-specific resource IDs/properties | Link discovery; tolerant parsing; `vendor_ids` scenario |
| Flaky tests from shared server state | Per-test scenario reset; random port; no sleeps in assertions |
| Secret leakage in logs/reports | Env-only credentials; `repr=False`; SUP-RF-06 |
| Misreading "BMC on" as "healthy" | Explicit aggregation policy (Phase 4) with dedicated tests |
