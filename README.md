# Hardware-Aware GPU Server Validation Framework

A Python/pytest framework that validates GPU servers by combining **BMC data over Redfish** with
**Linux host data**, and (in a later phase) turns detected failures into standardized
infrastructure events for a GPU-pool resource-allocation simulator.

> **Status: Milestone 1 (Phase 0 + Phase 1) complete.** Mock Redfish server, Redfish client,
> power-state collector and TC01–TC03 are implemented and passing. Everything else is planned
> and marked as such. All BMC data is **simulated**; no real hardware has been tested yet.

## Motivation

My graduate research studies GPU cloud resource allocation with a Multi-Leader Multi-Follower
Stackelberg game (GPU pools, job migration, switching costs, completion). That model assumes pools
are available. This project asks the practical infrastructure question behind that assumption:
*when a GPU server fails, how do we automatically detect, validate, record and quantify the impact
on GPU workloads?*

Key principle: **BMC "power on" is not the same as "healthy".** A server can be powered on with
normal temperatures while its GPU driver has failed; only combining BMC and host views catches that.

## Architecture (current + planned)

```
 ┌──────────────┐  Redfish/HTTPS   ┌────────────────────┐
 │ BMC / mock   │ ◄──────────────► │ bmc/  (client,     │──┐
 │ (OpenBMC)    │                  │  collectors)       │  │   ┌──────────────┐   ┌──────────┐   ┌────────────┐
 └──────────────┘                  └────────────────────┘  ├──►│ validation/  │──►│ events/  │──►│ simulator/ │
 ┌──────────────┐  SSH / local     ┌────────────────────┐  │   │ (aggregation)│   │ (schema, │   │ (A_p(t)    │
 │ Linux host   │ ◄──────────────► │ host/ (GPU, logs)  │──┘   └──────────────┘   │  adapter)│   │  demo sim) │
 └──────────────┘                  └────────────────────┘                        └──────────┘   └────────────┘
                     tests/ (pytest + evidence plugin) ──► reports/ (JSON, HTML, JUnit XML)
```

Details: [docs/architecture.md](docs/architecture.md).

## Technology stack

Python 3.10+ (verified on 3.13) · requests · FastAPI + uvicorn (mock BMC) · PyYAML · pytest ·
pytest-html. Target OS: Ubuntu 24.04.

## Installation

```bash
git clone <this-repo> gpu-server-validation && cd gpu-server-validation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional; fill in only for a real BMC. Never commit .env
```

## Running the mock Redfish server

```bash
# Scenario via CLI option, or MOCK_SCENARIO env var, or config/test_config.yaml
.venv/bin/python -m mocks.mock_redfish_server --scenario normal --port 8000

# Optional Basic auth (service root stays public, as in Redfish)
MOCK_REDFISH_USERNAME=demo MOCK_REDFISH_PASSWORD=demo-pass \
  .venv/bin/python -m mocks.mock_redfish_server --scenario sensor_warning
```

| Scenario | Meaning |
|---|---|
| `normal` | A: power On, sensors OK, no critical events, host healthy |
| `sensor_warning` | B: CPU0 88 °C > 85 °C warning threshold, health Warning, host healthy |
| `host_gpu_failure` | C: BMC fully healthy, host GPU driver error |
| `powered_off` | D: power Off, host unreachable |
| `vendor_ids` | Normal data at `Systems/Self`, `Chassis/1` (tests link discovery) |

Runtime control (not Redfish, test orchestration only):

```bash
curl -X PUT  localhost:8000/mock/scenario -H 'Content-Type: application/json' -d '{"name":"powered_off"}'
curl -X PUT  localhost:8000/mock/fault    -H 'Content-Type: application/json' -d '{"status_code":503}'
curl -X DELETE localhost:8000/mock/fault
curl localhost:8000/mock/scenarios
```

## Querying a BMC (mock or real, read-only)

```bash
REDFISH_BASE_URL=http://127.0.0.1:8000 REDFISH_USERNAME=demo REDFISH_PASSWORD=demo-pass \
  .venv/bin/python -m bmc
```

Example output (mock, scenario `sensor_warning`):

```json
{
  "base_url": "http://127.0.0.1:8000",
  "redfish_version": "1.17.0",
  "product": "Mock Redfish Service (SIMULATED)",
  "system_uri": "/redfish/v1/Systems/system",
  "chassis_uri": "/redfish/v1/Chassis/chassis",
  "power": {"raw_value": "On", "state": "ON", "system_health": "Warning",
            "source_uri": "/redfish/v1/Systems/system"}
}
```

## Running the tests

```bash
.venv/bin/python -m pytest -v
```

The suite starts its own mock server on a random loopback port with random per-run credentials;
no BMC, GPU or network access is needed. Outputs:

* `reports/test_results.json` – structured evidence per test (ID, objective, preconditions, steps,
  expected, actual, PASS/FAIL/WARNING/SKIPPED)
* `reports/report.html` – pytest-html report with a Test ID column and evidence block
* `reports/junit.xml` – for CI

Latest run (2026-11-18, Python 3.13.18, Ubuntu 24.04.5): **32 passed, 0 failed** —
see [docs/test_cases.md](docs/test_cases.md).

## Implementation status

| Area | Status |
|---|---|
| Mock Redfish server (5 scenarios, auth, fault injection) | ✅ done |
| Redfish client (discovery, auth, timeout, TLS, error types) | ✅ done |
| Power-state collector / interpretation | ✅ done |
| TC01–TC03 + 6 supplementary client tests, JSON/HTML evidence | ✅ done |
| Sensor/event-log collectors (TC04–TC06) | ⏳ Phase 2 |
| Host collectors: system, logs, GPU (nvidia-smi → ROCm), SSH (TC07–TC09) | ⏳ Phase 3 |
| Validation engine + aggregation policy (TC10–TC12) | ⏳ Phase 4 |
| Event schema + adapter | ⏳ Phase 6 |
| GPU-pool failure demo simulator (S0–S3) | ⏳ Phase 7 |

Files for planned phases exist as documented stubs only.

## Known limitations

* Only tested against the mock; behavior against real OpenBMC / vendor BMCs is **unverified**.
* Uses legacy `Power`/`Thermal` resources; `PowerSubsystem`/`ThermalSubsystem` not yet handled.
* Discovery uses the first member of `Systems`/`Chassis` (single-node servers).
* Basic auth only (no Redfish session tokens yet). No response caching (discovery re-reads the root).
* Mock control endpoints are unauthenticated and bound to 127.0.0.1 by default.

## Future development

Phase 2 sensor and event-log classification → Phase 3 host collectors → Phase 4 aggregation engine →
Phase 6 events → Phase 7 pool-availability simulator (A_p(t) ∈ {0,1}; capacity stays exogenous) →
later: OpenBMC in QEMU as a real Redfish target.
