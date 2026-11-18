# Test Cases

Actual results below are from the run on **2026-11-18** (`python -m pytest -v`, Python 3.13.18,
Ubuntu 24.04.5, mock Redfish server with SIMULATED data), Phase 2 branch: **61 passed, 0 failed**.
Per-test evidence: `reports/test_results.json` (regenerated on every run).

## Core test cases

| ID | Name | Preconditions | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|---|
| TC01 | Redfish service root is accessible | Mock running, scenario `normal` | GET `/redfish/v1/`; check version and links | 200, `RedfishVersion`, links to Systems/Chassis | RedfishVersion=1.17.0, `@odata.id=/redfish/v1/`, Systems/Chassis links present | PASS |
| TC02 | Power state can be retrieved | Mock running, valid credentials | Discover system; `collect_power_state()` (4 scenarios) | Non-empty raw PowerState + source URI | `On` (normal, sensor_warning, host_gpu_failure), `Off` (powered_off), from `/redfish/v1/Systems/system` | PASS (4/4) |
| TC03 | Power state is interpreted correctly | Unit: none. E2E: mock running | `interpret_power_state()` on 11 raw values; E2E on 4 scenarios | Valid values map correctly; missing/invalid → UNKNOWN (never ON); E2E On→ON, Off→OFF | All 11 unit mappings correct (incl. `None`, `""`, `"Standby"`, `1` → UNKNOWN); E2E ON×3, OFF×1 | PASS (15/15) |
| TC04 | Normal temperature classified healthy | Scenario `normal`, `thresholds.yaml` | `collect_sensors()`; inspect 4 temperature sensors | All HEALTHY (framework and BMC), report HEALTHY | CPU0 52, CPU1 54, GPU0 61, Inlet 24 °C → HEALTHY; report HEALTHY; no unknown/missing | PASS |
| TC05 | Temperature above warning threshold → warning | Scenario `sensor_warning` (CPU0 88 °C, CPU warn 85) + unit boundaries | `collect_sensors()`; `classify_temperature()` on 84.9/85/94.9/95/120/None/"hot" | CPU0 WARNING citing 85 °C, others HEALTHY, report WARNING; <85 H, ≥85 W, ≥95 C, missing UNKNOWN | CPU0 88 °C → WARNING ("88.0 C >= warning threshold 85.0 C"); report WARNING; all 7 boundaries as expected | PASS (8/8) |
| TC06 | Event logs retrieved and parsed | Scenarios `normal`, `sensor_warning` | `collect_event_log()`; check count, IDs, UTC timestamps, severities | normal: 2×OK → HEALTHY; sensor_warning: OK+Warning → WARNING; no anomalies | As expected in both; all timestamps aware UTC; 0 anomalies | PASS (2/2) |
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

## Supplementary sensor and event-log tests (Phase 2)

| ID | Name | Expected | Actual | Status |
|---|---|---|---|---|
| SUP-SN-01 | Framework/BMC disagreement → worse value + note | 90 °C & BMC OK → WARNING; 50 °C & BMC Critical → CRITICAL; 50 °C & BMC Warning → WARNING | As expected, each with `disagreement:` note | PASS (3/3) |
| SUP-SN-02 | Fan and voltage classification | 7000 H, 1500 W, 900 C RPM; % fan not RPM-checked; 12.0 V H, 13.1/11.0 V C | As expected | PASS |
| SUP-SN-03 | Critical sensors end-to-end (scenario E) | GPU0 93 °C C, Fan2 800 RPM C, report C | As expected | PASS |
| SUP-SN-04 | Incomplete BMC data (`sparse_sensors`) | No exception; CPU1 UNKNOWN & listed; absent Fan2 excluded; report HEALTHY | As expected | PASS |
| SUP-SN-05 | Invalid threshold config rejected | ConfigError for inverted / no default / non-numeric | ConfigError ×3 | PASS (3/3) |
| SUP-EV-01 | Critical SEL event (scenario E) | CRITICAL; latest critical = entry 3 at 10:05:42Z | As expected | PASS |
| SUP-EV-02 | `since` window | since 10:03 → CRITICAL; since 10:10 → HEALTHY with all 3 events still returned; naive `since` → ValueError | As expected | PASS |
| SUP-EV-03 | Malformed event fields (`sparse_sensors`) | created None; naive ts → UTC; "Informational" → UNKNOWN; 2 anomalies; HEALTHY | As expected | PASS |
| SUP-EV-04 | Timestamp normalization (unit) | Z / +08:00 / naive → UTC; invalid → None | 6/6 as expected | PASS (6/6) |

Defect found and fixed during Phase 2: the first run failed 2 TC05 boundary cases (reading
`None` / `"hot"` with BMC Health `OK` was classified HEALTHY). Policy corrected: no reading → UNKNOWN
unless the BMC reports Warning/Critical. Re-run: all pass.

The evidence plugin was also checked against a deliberately failing temporary test (asserting ON in
`powered_off`): it was recorded as `FAIL` with actual `state=OFF`. That test was removed afterwards.
