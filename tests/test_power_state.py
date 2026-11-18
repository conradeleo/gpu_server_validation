"""TC02 (power state retrieval) and TC03 (power state interpretation)."""

from __future__ import annotations

import pytest

from bmc.power_collector import PowerState, collect_power_state, interpret_power_state
from bmc.redfish_client import RedfishClient

SCENARIOS_ON = ["normal", "sensor_warning", "host_gpu_failure"]


@pytest.mark.tc(
    id="TC02",
    objective="Power state can be retrieved from the BMC.",
    preconditions=["Mock Redfish server running", "Valid credentials"],
    steps=["Discover the ComputerSystem from the service root",
           "Read PowerState and Status.Health via collect_power_state()"],
    expected="A non-empty raw PowerState string is returned together with its source URI.",
)
@pytest.mark.parametrize(
    "scenario_name",
    [pytest.param(s, marks=pytest.mark.scenario(s)) for s in [*SCENARIOS_ON, "powered_off"]],
)
def test_tc02_power_state_retrieved(redfish_client: RedfishClient, scenario_name: str, evidence) -> None:
    result = collect_power_state(redfish_client)
    evidence.record(f"[{scenario_name}] {result.as_dict()}", power=result.as_dict())
    assert isinstance(result.raw_value, str) and result.raw_value
    assert result.source_uri == "/redfish/v1/Systems/system"


@pytest.mark.tc(
    id="TC03",
    objective="Raw Redfish PowerState values are interpreted correctly (unit level).",
    preconditions=["None (pure function)"],
    steps=["Call interpret_power_state() with each raw value"],
    expected="Valid Redfish values map to their state; missing/invalid values map to UNKNOWN, never ON.",
)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("On", PowerState.ON),
        ("Off", PowerState.OFF),
        ("PoweringOn", PowerState.POWERING_ON),
        ("PoweringOff", PowerState.POWERING_OFF),
        ("Paused", PowerState.PAUSED),
        ("on", PowerState.ON),            # casing deviation tolerated
        (" Off ", PowerState.OFF),        # whitespace tolerated
        (None, PowerState.UNKNOWN),       # property missing
        ("", PowerState.UNKNOWN),
        ("Standby", PowerState.UNKNOWN),  # not a Redfish PowerState value
        (1, PowerState.UNKNOWN),          # wrong type
    ],
)
def test_tc03_power_state_interpretation(raw: object, expected: PowerState, evidence) -> None:
    actual = interpret_power_state(raw)
    evidence.record(f"interpret_power_state({raw!r}) -> {actual.value}")
    assert actual is expected


@pytest.mark.tc(
    id="TC03",
    objective="Power state reported by the BMC is interpreted correctly end-to-end.",
    preconditions=["Mock Redfish server running"],
    steps=["Activate scenario", "collect_power_state()", "Compare normalized state"],
    expected="normal/sensor_warning/host_gpu_failure -> ON; powered_off -> OFF.",
)
@pytest.mark.parametrize(
    ("scenario_name", "expected"),
    [pytest.param(s, PowerState.ON, marks=pytest.mark.scenario(s)) for s in SCENARIOS_ON]
    + [pytest.param("powered_off", PowerState.OFF, marks=pytest.mark.scenario("powered_off"))],
)
def test_tc03_power_state_interpreted_from_bmc(
    redfish_client: RedfishClient, scenario_name: str, expected: PowerState, evidence
) -> None:
    result = collect_power_state(redfish_client)
    evidence.record(f"[{scenario_name}] raw={result.raw_value!r} -> {result.state.value} "
                    f"(system health={result.system_health})")
    assert result.state is expected
