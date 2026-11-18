"""Builders that turn a scenario dict into Redfish-style JSON payloads.

The payload shapes follow the DMTF Redfish schemas used by OpenBMC (ServiceRoot,
ComputerSystem, Chassis, Power, Thermal, LogEntryCollection) but only include a
representative subset of properties. All values are simulated.
"""

from __future__ import annotations

from typing import Any

ROOT = "/redfish/v1"


def _status(health: str, state: str = "Enabled") -> dict[str, str]:
    return {"State": state, "Health": health}


def redfish_error(code: str, message: str) -> dict[str, Any]:
    """Redfish-style error body (DMTF Base message registry format)."""
    return {
        "error": {
            "code": f"Base.1.13.{code}",
            "message": message,
            "@Message.ExtendedInfo": [
                {
                    "@odata.type": "#Message.v1_1_1.Message",
                    "MessageId": f"Base.1.13.{code}",
                    "Message": message,
                    "Severity": "Critical",
                    "Resolution": "None.",
                }
            ],
        }
    }


def service_root(sc: dict[str, Any]) -> dict[str, Any]:
    return {
        "@odata.id": f"{ROOT}/",
        "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot",
        "Id": "RootService",
        "Name": "Root Service",
        "RedfishVersion": "1.17.0",
        "UUID": "00000000-0000-4000-8000-000000000001",
        "Product": "Mock Redfish Service (SIMULATED)",
        "Systems": {"@odata.id": f"{ROOT}/Systems"},
        "Chassis": {"@odata.id": f"{ROOT}/Chassis"},
        "Managers": {"@odata.id": f"{ROOT}/Managers"},
        "Oem": {"Mock": {"Simulated": True, "Scenario": sc["name"]}},
    }


def collection(kind: str, odata_type: str, member_ids: list[str]) -> dict[str, Any]:
    return {
        "@odata.id": f"{ROOT}/{kind}",
        "@odata.type": f"#{odata_type}",
        "Name": f"{kind} Collection",
        "Members": [{"@odata.id": f"{ROOT}/{kind}/{mid}"} for mid in member_ids],
        "Members@odata.count": len(member_ids),
    }


def computer_system(sc: dict[str, Any]) -> dict[str, Any]:
    sid = sc["resource_ids"]["system"]
    cid = sc["resource_ids"]["chassis"]
    s = sc["system"]
    return {
        "@odata.id": f"{ROOT}/Systems/{sid}",
        "@odata.type": "#ComputerSystem.v1_20_0.ComputerSystem",
        "Id": sid,
        "Name": "Simulated GPU Server",
        "SystemType": "Physical",
        "Model": s.get("model"),
        "SerialNumber": s.get("serial_number"),
        "BiosVersion": s.get("bios_version"),
        "PowerState": s.get("power_state"),
        "Status": _status(s.get("health", "OK")),
        "LogServices": {"@odata.id": f"{ROOT}/Systems/{sid}/LogServices"},
        "Links": {"Chassis": [{"@odata.id": f"{ROOT}/Chassis/{cid}"}]},
    }


def chassis(sc: dict[str, Any]) -> dict[str, Any]:
    cid = sc["resource_ids"]["chassis"]
    sid = sc["resource_ids"]["system"]
    return {
        "@odata.id": f"{ROOT}/Chassis/{cid}",
        "@odata.type": "#Chassis.v1_23_0.Chassis",
        "Id": cid,
        "Name": "Simulated Chassis",
        "ChassisType": "RackMount",
        "PowerState": sc["system"].get("power_state"),
        "Status": _status(sc["system"].get("health", "OK")),
        "Power": {"@odata.id": f"{ROOT}/Chassis/{cid}/Power"},
        "Thermal": {"@odata.id": f"{ROOT}/Chassis/{cid}/Thermal"},
        "Links": {"ComputerSystems": [{"@odata.id": f"{ROOT}/Systems/{sid}"}]},
    }


def power(sc: dict[str, Any]) -> dict[str, Any]:
    cid = sc["resource_ids"]["chassis"]
    base = f"{ROOT}/Chassis/{cid}/Power"
    return {
        "@odata.id": base,
        "@odata.type": "#Power.v1_7_1.Power",
        "Id": "Power",
        "Name": "Power",
        "PowerControl": [
            {
                "@odata.id": f"{base}#/PowerControl/0",
                "MemberId": "0",
                "Name": "Chassis Power Control",
                "PowerConsumedWatts": sc.get("power_consumed_watts"),
            }
        ],
        "Voltages": [
            {
                "@odata.id": f"{base}#/Voltages/{i}",
                "MemberId": str(i),
                "Name": v["name"],
                "ReadingVolts": v["reading"],
                "LowerThresholdCritical": v.get("lower_critical"),
                "UpperThresholdCritical": v.get("upper_critical"),
                "Status": _status(v.get("health", "OK")),
            }
            for i, v in enumerate(sc["voltages"])
        ],
    }


def thermal(sc: dict[str, Any]) -> dict[str, Any]:
    cid = sc["resource_ids"]["chassis"]
    base = f"{ROOT}/Chassis/{cid}/Thermal"
    return {
        "@odata.id": base,
        "@odata.type": "#Thermal.v1_7_1.Thermal",
        "Id": "Thermal",
        "Name": "Thermal",
        "Temperatures": [
            {
                "@odata.id": f"{base}#/Temperatures/{i}",
                "MemberId": str(i),
                "Name": t["name"],
                "PhysicalContext": t.get("context"),
                "ReadingCelsius": t["reading"],
                "UpperThresholdNonCritical": t.get("upper_noncritical"),
                "UpperThresholdCritical": t.get("upper_critical"),
                "Status": _status(t.get("health", "OK")),
            }
            for i, t in enumerate(sc["temperatures"])
        ],
        "Fans": [
            {
                "@odata.id": f"{base}#/Fans/{i}",
                "MemberId": str(i),
                "Name": f["name"],
                "Reading": f["reading"],
                "ReadingUnits": "RPM",
                "LowerThresholdCritical": f.get("lower_critical"),
                "Status": _status(f.get("health", "OK")),
            }
            for i, f in enumerate(sc["fans"])
        ],
    }


def log_services(sc: dict[str, Any]) -> dict[str, Any]:
    sid = sc["resource_ids"]["system"]
    base = f"{ROOT}/Systems/{sid}/LogServices"
    return {
        "@odata.id": base,
        "@odata.type": "#LogServiceCollection.LogServiceCollection",
        "Name": "System Log Services",
        "Members": [{"@odata.id": f"{base}/EventLog"}],
        "Members@odata.count": 1,
    }


def event_log_service(sc: dict[str, Any]) -> dict[str, Any]:
    sid = sc["resource_ids"]["system"]
    base = f"{ROOT}/Systems/{sid}/LogServices/EventLog"
    return {
        "@odata.id": base,
        "@odata.type": "#LogService.v1_3_0.LogService",
        "Id": "EventLog",
        "Name": "System Event Log Service",
        "Entries": {"@odata.id": f"{base}/Entries"},
    }


def log_entry(sc: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    sid = sc["resource_ids"]["system"]
    return {
        "@odata.id": f"{ROOT}/Systems/{sid}/LogServices/EventLog/Entries/{ev['id']}",
        "@odata.type": "#LogEntry.v1_15_0.LogEntry",
        "Id": str(ev["id"]),
        "Name": "System Event Log Entry",
        "EntryType": "Event",
        "Severity": ev.get("severity", "OK"),
        "Created": ev.get("created"),
        "MessageId": ev.get("message_id"),
        "Message": ev.get("message"),
    }


def log_entries(sc: dict[str, Any]) -> dict[str, Any]:
    sid = sc["resource_ids"]["system"]
    members = [log_entry(sc, ev) for ev in sc["events"]]
    return {
        "@odata.id": f"{ROOT}/Systems/{sid}/LogServices/EventLog/Entries",
        "@odata.type": "#LogEntryCollection.LogEntryCollection",
        "Name": "System Event Log Entries",
        "Members": members,
        "Members@odata.count": len(members),
    }
