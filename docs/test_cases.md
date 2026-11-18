# Test Cases

Actual results below are from the run on **2026-11-18** (`python -m pytest -v`, Python 3.13.18,
Ubuntu 24.04.5, mock Redfish server with SIMULATED data): **32 passed, 0 failed**.
Per-test evidence: `reports/test_results.json` (regenerated on every run).

## Core test cases

| ID | Name | Preconditions | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC01 | Redfish service root is accessible | Mock running, scenario `normal` | GET `/redfish/v1/`; check version and links | 200, `RedfishVersion`, links to Systems/Chassis | RedfishVersion=1.17.0, `@odata.id=/redfish/v1/`, Systems/Chassis links present | PASS |
| TC02 | Power state can be retrieved | Mock running, valid credentials | Discover system; `collect_power_state()` (4 scenarios) | Non-empty raw PowerState + source URI | `On` (normal, sensor_warning, host_gpu_failure), `Off` (powered_off), from `/redfish/v1/Systems/system` | PASS (4/4) |
| TC03 | Power state is interpreted correctly | Unit: none. E2E: mock running | `interpret_power_state()` on 11 raw values; E2E on 4 scenarios | Valid values map correctly; missing/invalid → UNKNOWN (never ON); E2E On→ON, Off→OFF | All 11 unit mappings correct (incl. `None`, `""`, `"Standby"`, `1` → UNKNOWN); E2E ON×3, OFF×1 | PASS (15/15) |
| TC04 | Normal temperature classified healthy | — | — | — | — | NOT RUN (Phase 2) |
| TC05 | Temperature above warning threshold → warning | — | — | — | — | NOT RUN (Phase 2) |
| TC06 | Event logs retrieved and parsed | — | — | — | — | NOT RUN (Phase 2) |
| TC07 | Host system information collected | — | — | — | — | NOT RUN (Phase 3) |
| TC08 | Missing NVIDIA GPU handled correctly | — | — | — | — | NOT RUN (Phase 3) |
| TC09 | GPU driver error → degraded | — | — | — | — | NOT RUN (Phase 3/4) |
| TC10 | BMC healthy + host GPU error → degraded | — | — | — | — | NOT RUN (Phase 4) |
| TC11 | BMC unavailable handled correctly | — | — | — | — | NOT RUN (Phase 4) |
| TC12 | Regression of previous cases | — | — | — | — | NOT RUN (Phase 4) |

## Supplementary Redfish client tests

| ID | Name | Expected | Actual | Status |
|---|---|---|---|---|
| SUP-RF-01 | All 6 minimum endpoints return Redfish JSON | 200, `@odata.id` == URI | 6/6 matched | PASS |
| SUP-RF-02 | Link discovery with vendor IDs | `/Systems/Self`, `/Chassis/1`; `/Systems/system` → 404 | As expected; Power/Thermal/event log loaded via links | PASS |
| SUP-RF-03 | Auth failure → `RedfishAuthError` | 401 for wrong/no credentials; root stays public | Both raised `RedfishAuthError` (HTTP 401) | PASS (2/2) |
| SUP-RF-04 | BMC 503 → `RedfishHTTPError` with Redfish message | status 503 + `error.message` | 503, message parsed | PASS |
| SUP-RF-05 | Unreachable BMC → `RedfishConnectionError` | error within timeout | Raised | PASS |
| SUP-RF-06 | Password not in logs or `repr` | absent | absent | PASS |

The evidence plugin was also checked against a deliberately failing temporary test (asserting ON in
`powered_off`): it was recorded as `FAIL` with actual `state=OFF`. That test was removed afterwards.
