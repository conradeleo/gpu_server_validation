# Experiment Results

This file records **actual** outputs only. Nothing here is fabricated; anything not yet executed
is marked NOT RUN. Simulated results are always labelled as simulated and are never presented as
real hardware measurements.

## Hardware validation

| Target | Status |
|---|---|
| Mock Redfish server (simulated) | Executed — see `docs/test_cases.md` (2026-11-18: 32/32 PASS) |
| OpenBMC in QEMU | NOT RUN |
| Real BMC / GPU server | NOT RUN |

## GPU-pool failure simulation (Phase 7, simulated)

| Scenario | No Migration | Immediate Migration | Switching-cost-aware Migration |
|---|---|---|---|
| S0 Normal operation | NOT RUN | NOT RUN | NOT RUN |
| S1 Temporary pool failure | NOT RUN | NOT RUN | NOT RUN |
| S2 Failure and recovery | NOT RUN | NOT RUN | NOT RUN |
| S3 Failure under competition | NOT RUN | NOT RUN | NOT RUN |

Metrics to report once run: job completion rate, average waiting time, migration count,
switching cost, recovery time, job-level and aggregate outcomes.
