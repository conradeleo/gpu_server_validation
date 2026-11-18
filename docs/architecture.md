# Architecture

Status legend: ✅ implemented (Milestone 1) · ⏳ planned.

## 1. BMC monitoring (✅ partial)

```
RedfishClient.get(uri)            -- the only HTTP entry point (GET only)
  ├─ get_service_root()           /redfish/v1/
  ├─ system_uri() / chassis_uri() root.Systems / root.Chassis -> Members[0]
  ├─ get_system() / get_chassis()
  ├─ get_power() / get_thermal()  chassis.Power / chassis.Thermal links
  └─ get_event_logs()             system.LogServices -> EventLog (or first) -> Entries
bmc/power_collector.py            PowerState interpretation           ✅
bmc/sensor_collector.py           temp/fan/voltage classification     ✅ Phase 2
bmc/event_log_collector.py        LogEntry parsing + severity summary ✅ Phase 2
common/status.py                  HealthStatus model + worst-of       ✅ Phase 2
```

### Sensor classification (Phase 2)

Each sensor gets two independent opinions, both recorded in `SensorReading`:

| Source | Temperature | Fan | Voltage |
|---|---|---|---|
| Framework | `thresholds.yaml` by `PhysicalContext` (CPU/GPU/Intake/default): `>= warning` WARNING, `>= critical` CRITICAL | `thresholds.yaml` RPM: `< warning_below` WARNING, `< critical_below` CRITICAL; non-RPM units not checked | BMC-published `Lower/UpperThresholdCritical`: outside → CRITICAL |
| BMC | `Status.Health` OK/Warning/Critical | same | same |

Rules:
1. Final sensor status = worse of the two opinions. Disagreements get a `disagreement:` note,
   so a BMC reporting `OK` for an over-threshold reading is never silently trusted.
2. No reading → UNKNOWN, unless the BMC itself reports Warning/Critical (escalation only).
   A bare BMC `OK` without a value is not accepted as evidence of health.
3. `Status.State` Absent/Disabled → recorded, excluded from aggregation.
4. Report status = worst known status of present sensors; present-but-UNKNOWN sensors are listed
   in `unknown_sensors` rather than hidden. Missing `Thermal`/`Power` resources (404, no link)
   are listed in `missing_resources`; connection/auth errors propagate.
5. Threshold files are validated on load (numeric, warning < critical, defaults present).

### Event log (Phase 2)

`LogEntry` → `LogEvent` (UTC timestamp, severity as HealthStatus). Naive timestamps are assumed
UTC; invalid timestamps and non-standard severities become `None`/UNKNOWN and are listed as
anomalies (they do not escalate status). Summary status = worst severity among *considered*
events; an optional `since` window (e.g. start of a validation run) keeps resolved historical
events from holding a server CRITICAL indefinitely, while all events are still returned.

Design decisions:

* **Link discovery, not hardcoded IDs.** OpenBMC uses `Systems/system`; other BMCs use `Self`, `1`,
  `System.Embedded.1`. The client follows `@odata.id` links. Verified by the `vendor_ids` scenario.
* **Typed errors** so later phases can distinguish *why* the BMC view is missing:
  `RedfishConnectionError` (unreachable/timeout/TLS), `RedfishAuthError` (401/403),
  `RedfishHTTPError` (other status, with Redfish `error.message`), `RedfishResponseError`
  (invalid JSON / missing link). This matters for Case 4 (BMC unavailable) in the aggregation policy.
* **Credentials** come only from arguments or `REDFISH_*` env vars; `password` is excluded from
  `repr`, and only method, path, status and latency are logged (verified by SUP-RF-06).
* **Power interpretation** is fail-safe: missing/unknown values become `UNKNOWN`, never `ON`.

### Mock Redfish server

FastAPI app built from `config/mock_scenarios.yaml` (scenarios shallow-merge over `defaults`).
Payload shapes follow DMTF schemas used by OpenBMC (ServiceRoot, ComputerSystem, Chassis,
Power, Thermal, LogService, LogEntryCollection) with a representative subset of properties.

Simplifying assumptions of the mock (documented, intentional):

* One system, one chassis, one `EventLog` log service; log entries are expanded inline.
* Legacy `Power`/`Thermal` only; no `PowerSubsystem`/`ThermalSubsystem`, no `Managers/bmc` details.
* Basic auth only (no `SessionService`); service root is public as Redfish requires.
* Fault injection returns the same error for every `/redfish` path.
* The `host` block in scenarios is not served over Redfish; it feeds `mocks/mock_host_status.py` (Phase 3).

## 2. Linux host monitoring (⏳ Phase 3)

Modular collectors: system info, `journalctl`/`dmesg` (no root; permission errors reported, not
raised), GPU via a backend interface (`NvidiaSmiBackend` first, `RocmSmiBackend` later). Absence of
`nvidia-smi` yields `GPU_MONITORING_UNAVAILABLE`, which is **not** a hardware failure.

## 3. Validation engine (⏳ Phase 4)

Status model (`common/status.py`, already used by Phase 2 collectors): `HEALTHY < WARNING < DEGRADED < CRITICAL`, plus `UNKNOWN`.
Planned aggregation policy (BMC state and host state are always recorded next to the system state):

| BMC | Host | System | Rationale |
|---|---|---|---|
| HEALTHY | HEALTHY | HEALTHY | |
| WARNING | HEALTHY | WARNING | worst-of |
| HEALTHY | DEGRADED (GPU driver error) | DEGRADED | power-on ≠ healthy |
| UNKNOWN (unreachable) | HEALTHY | WARNING | workloads run, but out-of-band visibility is lost |
| UNKNOWN | UNKNOWN | UNKNOWN | no evidence either way |
| CRITICAL | any failure | CRITICAL | worst-of |

Rule: system = worst of known domain states; if one domain is UNKNOWN and the other HEALTHY,
system = WARNING; if both UNKNOWN, system = UNKNOWN. To be implemented and tested in TC09–TC11.

## 4. Event adapter (⏳ Phase 6)

Validation results → normalized events (`POOL_UNAVAILABLE`, `POOL_DEGRADED`, `POOL_RECOVERED`,
`GPU_DRIVER_ERROR`, `HOST_UNREACHABLE`, `SENSOR_THRESHOLD_EXCEEDED`), ISO 8601 UTC timestamps.
The adapter depends on validation results only, never on Redfish payloads.

## 5. GPU-pool simulator integration (⏳ Phase 7)

Adds only an availability variable A_p(t) ∈ {0,1}. Pool capacity remains exogenous; the
Stackelberg model is not modified. Since the thesis simulator is not in this repository, a small
independent demo simulator plus an adapter interface will be built.

## 6. Data flow

```
Redfish JSON ─► bmc collectors ─┐
                                ├─► validation (per-domain + system status) ─► events ─► simulator
host commands ─► host collectors┘                        │
                                                         └─► pytest evidence ─► reports/*.json|html|xml
```
