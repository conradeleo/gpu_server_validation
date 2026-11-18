"""Temperature, fan and voltage collection with threshold classification.

Each sensor gets two independent opinions that are both recorded:

* **framework status** - from ``config/thresholds.yaml`` (temperature, fan RPM) or, for
  voltages, from the BMC-published critical range;
* **BMC status** - the sensor's own Redfish ``Status.Health``.

The sensor's final status is the worse of the two. When they disagree a note is added,
so a BMC that reports ``OK`` for an over-threshold reading is not silently trusted.
Sensors whose ``Status.State`` is ``Absent``/``Disabled`` are recorded but excluded
from aggregation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bmc.redfish_client import RedfishClient, RedfishHTTPError, RedfishResponseError
from common.config import ConfigError, load_yaml
from common.status import HealthStatus, from_redfish_health, worst

logger = logging.getLogger(__name__)

NOT_PRESENT_STATES = {"absent", "disabled", "unavailableoffline"}


# ----------------------------------------------------------------------------- thresholds
@dataclass(frozen=True)
class TempThreshold:
    warning: float
    critical: float


@dataclass(frozen=True)
class FanThreshold:
    warning_below: float
    critical_below: float


@dataclass(frozen=True)
class Thresholds:
    """Framework-side thresholds keyed by Redfish ``PhysicalContext`` (with a ``default``)."""

    temperature: dict[str, TempThreshold]
    fan: dict[str, FanThreshold]

    def temp_for(self, context: str | None) -> TempThreshold:
        return self.temperature.get(context or "", self.temperature["default"])

    def fan_for(self, name: str | None) -> FanThreshold:
        return self.fan.get(name or "", self.fan["default"])


def _num(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number, got {value!r}")
    return float(value)


def load_thresholds(path: str | Path = "config/thresholds.yaml") -> Thresholds:
    """Load and validate thresholds.

    Raises:
        ConfigError: on missing ``default`` entries, non-numeric values, or
            inverted limits (temperature warning >= critical, fan warning_below <= critical_below).
    """
    raw = load_yaml(path)
    temps: dict[str, TempThreshold] = {}
    for ctx, v in (raw.get("temperature_celsius") or {}).items():
        t = TempThreshold(_num(v.get("warning"), f"temperature_celsius.{ctx}.warning"),
                          _num(v.get("critical"), f"temperature_celsius.{ctx}.critical"))
        if t.warning >= t.critical:
            raise ConfigError(f"temperature_celsius.{ctx}: warning ({t.warning}) must be < critical ({t.critical})")
        temps[ctx] = t
    fans: dict[str, FanThreshold] = {}
    for name, v in (raw.get("fan_rpm") or {}).items():
        f = FanThreshold(_num(v.get("warning_below"), f"fan_rpm.{name}.warning_below"),
                         _num(v.get("critical_below"), f"fan_rpm.{name}.critical_below"))
        if f.warning_below <= f.critical_below:
            raise ConfigError(f"fan_rpm.{name}: warning_below must be > critical_below")
        fans[name] = f
    if "default" not in temps or "default" not in fans:
        raise ConfigError("thresholds must define temperature_celsius.default and fan_rpm.default")
    return Thresholds(temps, fans)


# ----------------------------------------------------------------------------- readings
@dataclass
class SensorReading:
    """One sensor with raw value, both opinions, and the final status."""

    kind: str  # temperature | fan | voltage
    name: str
    reading: float | None
    units: str | None
    context: str | None
    present: bool
    bmc_status: HealthStatus
    framework_status: HealthStatus
    status: HealthStatus
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        for k in ("bmc_status", "framework_status", "status"):
            d[k] = d[k].value
        return d


def _reading(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _status_block(sensor: dict[str, Any]) -> tuple[bool, HealthStatus]:
    st = sensor.get("Status") if isinstance(sensor.get("Status"), dict) else {}
    state = str(st.get("State") or "Enabled").lower()
    return state not in NOT_PRESENT_STATES, from_redfish_health(st.get("Health"))


def _finalize(r: SensorReading) -> SensorReading:
    """Combine framework and BMC opinions; record disagreements."""
    if not r.present:
        r.status = HealthStatus.UNKNOWN
        r.notes.append("sensor not present (Status.State Absent/Disabled); excluded from aggregation")
        return r
    fw, bmc = r.framework_status, r.bmc_status
    if r.reading is None and bmc.rank < HealthStatus.WARNING.rank:
        # No reading = no evidence. A bare BMC "OK" is not trusted, but a BMC-reported
        # Warning/Critical is still honored (escalation only).
        r.status = HealthStatus.UNKNOWN
        return r
    r.status = worst([fw, bmc])
    if HealthStatus.UNKNOWN not in (fw, bmc) and fw is not bmc:
        side = "framework threshold" if fw.rank > bmc.rank else "BMC Status.Health"
        r.notes.append(f"disagreement: framework={fw.value}, BMC={bmc.value}; {side} is more severe")
    return r


def classify_temperature(sensor: dict[str, Any], thresholds: Thresholds) -> SensorReading:
    """Classify one Redfish ``Thermal.Temperatures[]`` member."""
    present, bmc = _status_block(sensor)
    value, ctx = _reading(sensor.get("ReadingCelsius")), sensor.get("PhysicalContext")
    t = thresholds.temp_for(ctx)
    r = SensorReading("temperature", str(sensor.get("Name", "<unnamed>")), value, "Cel", ctx,
                      present, bmc, HealthStatus.UNKNOWN, HealthStatus.UNKNOWN)
    if value is None:
        r.notes.append("ReadingCelsius missing or non-numeric")
    elif value >= t.critical:
        r.framework_status = HealthStatus.CRITICAL
        r.notes.append(f"{value} C >= critical threshold {t.critical} C")
    elif value >= t.warning:
        r.framework_status = HealthStatus.WARNING
        r.notes.append(f"{value} C >= warning threshold {t.warning} C")
    else:
        r.framework_status = HealthStatus.HEALTHY
    return _finalize(r)


def classify_fan(sensor: dict[str, Any], thresholds: Thresholds) -> SensorReading:
    """Classify one Redfish ``Thermal.Fans[]`` member. Only RPM readings are threshold-checked."""
    present, bmc = _status_block(sensor)
    name = str(sensor.get("Name", "<unnamed>"))
    value, units = _reading(sensor.get("Reading")), sensor.get("ReadingUnits")
    t = thresholds.fan_for(name)
    r = SensorReading("fan", name, value, units, None, present, bmc, HealthStatus.UNKNOWN, HealthStatus.UNKNOWN)
    if value is None:
        r.notes.append("Reading missing or non-numeric")
    elif units != "RPM":
        r.notes.append(f"ReadingUnits={units!r}; RPM thresholds not applicable, relying on BMC health")
    elif value < t.critical_below:
        r.framework_status = HealthStatus.CRITICAL
        r.notes.append(f"{value} RPM < critical limit {t.critical_below} RPM")
    elif value < t.warning_below:
        r.framework_status = HealthStatus.WARNING
        r.notes.append(f"{value} RPM < warning limit {t.warning_below} RPM")
    else:
        r.framework_status = HealthStatus.HEALTHY
    return _finalize(r)


def classify_voltage(sensor: dict[str, Any]) -> SensorReading:
    """Classify one Redfish ``Power.Voltages[]`` member against its BMC-published critical range."""
    present, bmc = _status_block(sensor)
    value = _reading(sensor.get("ReadingVolts"))
    lo, hi = _reading(sensor.get("LowerThresholdCritical")), _reading(sensor.get("UpperThresholdCritical"))
    r = SensorReading("voltage", str(sensor.get("Name", "<unnamed>")), value, "V", None,
                      present, bmc, HealthStatus.UNKNOWN, HealthStatus.UNKNOWN)
    if value is None:
        r.notes.append("ReadingVolts missing or non-numeric")
    elif lo is None and hi is None:
        r.notes.append("no critical range published by BMC; relying on BMC health")
    elif (lo is not None and value < lo) or (hi is not None and value > hi):
        r.framework_status = HealthStatus.CRITICAL
        r.notes.append(f"{value} V outside critical range [{lo}, {hi}]")
    else:
        r.framework_status = HealthStatus.HEALTHY
    return _finalize(r)


# ----------------------------------------------------------------------------- report
@dataclass
class SensorReport:
    readings: list[SensorReading]
    missing_resources: list[str]

    @property
    def status(self) -> HealthStatus:
        """Worst status among present sensors; UNKNOWN if none could be evaluated."""
        return worst(r.status for r in self.readings if r.present)

    def by_kind(self, kind: str) -> list[SensorReading]:
        return [r for r in self.readings if r.kind == kind]

    def find(self, name: str) -> SensorReading:
        return next(r for r in self.readings if r.name == name)

    @property
    def unknown(self) -> list[str]:
        """Present sensors that could not be evaluated - reported, never hidden."""
        return [r.name for r in self.readings if r.present and r.status is HealthStatus.UNKNOWN]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "unknown_sensors": self.unknown,
            "missing_resources": self.missing_resources,
            "readings": [r.as_dict() for r in self.readings],
        }


def collect_sensors(client: RedfishClient, thresholds: Thresholds) -> SensorReport:
    """Collect and classify Thermal (temperatures, fans) and Power (voltages).

    A missing/unsupported resource (HTTP 404, absent link) is recorded in
    ``missing_resources`` instead of aborting; connection/auth errors propagate.
    """
    readings: list[SensorReading] = []
    missing: list[str] = []

    try:
        thermal = client.get_thermal()
        for s in thermal.get("Temperatures") or []:
            if isinstance(s, dict):
                readings.append(classify_temperature(s, thresholds))
        for s in thermal.get("Fans") or []:
            if isinstance(s, dict):
                readings.append(classify_fan(s, thresholds))
    except (RedfishHTTPError, RedfishResponseError) as exc:
        logger.warning("Thermal resource unavailable: %s", exc)
        missing.append(f"Thermal: {exc}")

    try:
        for s in client.get_power().get("Voltages") or []:
            if isinstance(s, dict):
                readings.append(classify_voltage(s))
    except (RedfishHTTPError, RedfishResponseError) as exc:
        logger.warning("Power resource unavailable: %s", exc)
        missing.append(f"Power: {exc}")

    return SensorReport(readings, missing)
