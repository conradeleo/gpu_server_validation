"""TC04 / TC05 (temperature classification) and supplementary sensor tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmc.redfish_client import RedfishClient
from bmc.sensor_collector import (
    Thresholds,
    classify_fan,
    classify_temperature,
    classify_voltage,
    collect_sensors,
    load_thresholds,
)
from common.config import ConfigError
from common.status import HealthStatus

H, W, C, U = HealthStatus.HEALTHY, HealthStatus.WARNING, HealthStatus.CRITICAL, HealthStatus.UNKNOWN


def temp(reading, context="CPU", health="OK", state="Enabled", name="T"):
    return {"Name": name, "PhysicalContext": context, "ReadingCelsius": reading,
            "Status": {"State": state, "Health": health}}


# ------------------------------------------------------------------------------------ TC04
@pytest.mark.tc(
    id="TC04",
    objective="Normal temperatures are classified as healthy.",
    preconditions=["Mock scenario A (normal)", "config/thresholds.yaml loaded"],
    steps=["collect_sensors()", "Inspect every temperature sensor and the sensor report status"],
    expected="All temperatures below their warning thresholds -> HEALTHY; report status HEALTHY.",
)
@pytest.mark.scenario("normal")
def test_tc04_normal_temperature_healthy(redfish_client: RedfishClient, thresholds: Thresholds, evidence) -> None:
    report = collect_sensors(redfish_client, thresholds)
    temps = report.by_kind("temperature")
    evidence.record("; ".join(f"{t.name}={t.reading}C->{t.status.value}" for t in temps)
                    + f"; report={report.status.value}", sensors=report.as_dict())

    assert len(temps) == 4
    assert all(t.status is H and t.framework_status is H and t.bmc_status is H for t in temps)
    assert report.status is H
    assert not report.unknown and not report.missing_resources


# ------------------------------------------------------------------------------------ TC05
@pytest.mark.tc(
    id="TC05",
    objective="A temperature above the configured warning threshold is classified as warning.",
    preconditions=["Mock scenario B (sensor_warning): CPU0 = 88 C, CPU warning threshold = 85 C"],
    steps=["collect_sensors()", "Inspect CPU0 Temp and the report status"],
    expected="CPU0 Temp -> WARNING with a note citing the 85 C threshold; other temps HEALTHY; report WARNING.",
)
@pytest.mark.scenario("sensor_warning")
def test_tc05_temperature_above_warning(redfish_client: RedfishClient, thresholds: Thresholds, evidence) -> None:
    report = collect_sensors(redfish_client, thresholds)
    cpu0 = report.find("CPU0 Temp")
    others = [t for t in report.by_kind("temperature") if t.name != "CPU0 Temp"]
    evidence.record(f"CPU0 Temp={cpu0.reading}C framework={cpu0.framework_status.value} "
                    f"bmc={cpu0.bmc_status.value} final={cpu0.status.value} notes={cpu0.notes}; "
                    f"report={report.status.value}", cpu0=cpu0.as_dict())

    assert cpu0.status is W and cpu0.framework_status is W
    assert any("warning threshold 85" in n for n in cpu0.notes)
    assert all(t.status is H for t in others)
    assert report.status is W


@pytest.mark.tc(
    id="TC05",
    objective="Temperature threshold boundaries are applied correctly (unit level, CPU: warn 85, crit 95).",
    preconditions=["config/thresholds.yaml loaded"],
    steps=["classify_temperature() on boundary readings with BMC health OK"],
    expected="<85 HEALTHY, >=85 WARNING, >=95 CRITICAL; missing reading UNKNOWN.",
)
@pytest.mark.parametrize(
    ("reading", "expected"),
    [(84.9, H), (85, W), (94.9, W), (95, C), (120, C), (None, U), ("hot", U)],
)
def test_tc05_temperature_boundaries(reading, expected: HealthStatus, thresholds: Thresholds, evidence) -> None:
    r = classify_temperature(temp(reading), thresholds)
    evidence.record(f"{reading!r} C -> {r.status.value} ({r.notes})")
    assert r.status is expected


# ------------------------------------------------------------------------------------ supplementary
@pytest.mark.tc(
    id="SUP-SN-01",
    objective="Disagreement between framework thresholds and BMC health is resolved to the worse value and recorded.",
    preconditions=["None (pure function)"],
    steps=["Classify a hot reading that the BMC reports OK", "Classify a normal reading that the BMC reports Critical"],
    expected="Both are escalated (WARNING / CRITICAL) and carry a 'disagreement' note.",
)
@pytest.mark.parametrize(
    ("reading", "bmc_health", "expected"),
    [(90, "OK", W), (50, "Critical", C), (50, "Warning", W)],
)
def test_framework_bmc_disagreement(reading, bmc_health, expected, thresholds: Thresholds, evidence) -> None:
    r = classify_temperature(temp(reading, health=bmc_health), thresholds)
    evidence.record(f"reading={reading} BMC={bmc_health} -> {r.status.value}; notes={r.notes}")
    assert r.status is expected
    assert any(n.startswith("disagreement") for n in r.notes)


@pytest.mark.tc(
    id="SUP-SN-02",
    objective="Fan and voltage readings are classified correctly (unit level).",
    preconditions=["fan_rpm.default: warning_below 2000, critical_below 1000"],
    steps=["classify_fan() on RPM/percent readings", "classify_voltage() inside/outside BMC critical range"],
    expected="Low RPM -> WARNING/CRITICAL; Percent units not RPM-checked; out-of-range voltage CRITICAL.",
)
def test_fan_and_voltage_classification(thresholds: Thresholds, evidence) -> None:
    def fan(reading, units="RPM", health="OK"):
        return {"Name": "FanX", "Reading": reading, "ReadingUnits": units, "Status": {"State": "Enabled", "Health": health}}

    def volt(reading):
        return {"Name": "P12V", "ReadingVolts": reading, "LowerThresholdCritical": 11.4,
                "UpperThresholdCritical": 12.6, "Status": {"State": "Enabled", "Health": "OK"}}

    results = {
        "fan 7000": classify_fan(fan(7000), thresholds).status,
        "fan 1500": classify_fan(fan(1500), thresholds).status,
        "fan 900": classify_fan(fan(900), thresholds).status,
        "fan 10% (Percent)": classify_fan(fan(10, "Percent"), thresholds),
        "volt 12.0": classify_voltage(volt(12.0)).status,
        "volt 13.1": classify_voltage(volt(13.1)).status,
        "volt 11.0": classify_voltage(volt(11.0)).status,
    }
    pct = results.pop("fan 10% (Percent)")
    evidence.record(f"{ {k: v.value for k, v in results.items()} }; percent fan -> "
                    f"framework={pct.framework_status.value}, final={pct.status.value}")
    assert results == {"fan 7000": H, "fan 1500": W, "fan 900": C, "volt 12.0": H, "volt 13.1": C, "volt 11.0": C}
    assert pct.framework_status is U and pct.status is H


@pytest.mark.tc(
    id="SUP-SN-03",
    objective="Critical BMC sensor conditions are classified CRITICAL end-to-end.",
    preconditions=["Mock scenario E (bmc_critical_host_failure): GPU0 93 C, Fan2 800 RPM"],
    steps=["collect_sensors()"],
    expected="GPU0 Temp CRITICAL, Fan2 CRITICAL, report CRITICAL.",
)
@pytest.mark.scenario("bmc_critical_host_failure")
def test_critical_sensors(redfish_client: RedfishClient, thresholds: Thresholds, evidence) -> None:
    report = collect_sensors(redfish_client, thresholds)
    gpu0, fan2 = report.find("GPU0 Temp"), report.find("Fan2")
    evidence.record(f"GPU0={gpu0.reading}C->{gpu0.status.value}, Fan2={fan2.reading}RPM->{fan2.status.value}, "
                    f"report={report.status.value}")
    assert gpu0.status is C and fan2.status is C and report.status is C


@pytest.mark.tc(
    id="SUP-SN-04",
    objective="Incomplete or irregular BMC sensor data is handled without errors and without hiding gaps.",
    preconditions=["Mock scenario sparse_sensors"],
    steps=["collect_sensors()", "Inspect missing reading, absent fan, percent fan, missing context"],
    expected="No exception; CPU1 (no reading) UNKNOWN and listed in unknown_sensors; absent Fan2 excluded; "
             "GPU0 without PhysicalContext uses default thresholds; report HEALTHY.",
)
@pytest.mark.scenario("sparse_sensors")
def test_sparse_sensor_data(redfish_client: RedfishClient, thresholds: Thresholds, evidence) -> None:
    report = collect_sensors(redfish_client, thresholds)
    evidence.record(f"report={report.status.value}, unknown={report.unknown}, "
                    f"absent={[r.name for r in report.readings if not r.present]}", sensors=report.as_dict())
    assert report.find("CPU1 Temp").status is U
    assert report.unknown == ["CPU1 Temp"]
    assert not report.find("Fan2").present
    assert report.find("GPU0 Temp").status is H
    assert report.status is H


@pytest.mark.tc(
    id="SUP-SN-05",
    objective="Invalid threshold configuration is rejected at load time.",
    preconditions=["Temporary thresholds file"],
    steps=["Write a file with warning >= critical", "Write a file without defaults", "load_thresholds()"],
    expected="ConfigError for each invalid file.",
)
@pytest.mark.parametrize(
    "content",
    [
        "temperature_celsius: {default: {warning: 90, critical: 80}}\nfan_rpm: {default: {warning_below: 2000, critical_below: 1000}}\n",
        "temperature_celsius: {CPU: {warning: 85, critical: 95}}\nfan_rpm: {default: {warning_below: 2000, critical_below: 1000}}\n",
        "temperature_celsius: {default: {warning: hot, critical: 95}}\nfan_rpm: {default: {warning_below: 2000, critical_below: 1000}}\n",
    ],
    ids=["inverted", "no_default", "non_numeric"],
)
def test_invalid_thresholds_rejected(tmp_path: Path, content: str, evidence) -> None:
    f = tmp_path / "thresholds.yaml"
    f.write_text(content)
    with pytest.raises(ConfigError) as exc:
        load_thresholds(f)
    evidence.record(f"ConfigError: {exc.value}")
