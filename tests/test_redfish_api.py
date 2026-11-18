"""TC01 and supplementary Redfish client robustness tests (all against the mock BMC)."""

from __future__ import annotations

import logging

import pytest

from bmc.redfish_client import (
    RedfishAuthError,
    RedfishClient,
    RedfishConfig,
    RedfishConnectionError,
    RedfishHTTPError,
)

MINIMUM_ENDPOINTS = [
    "/redfish/v1/",
    "/redfish/v1/Systems/system",
    "/redfish/v1/Chassis/chassis",
    "/redfish/v1/Chassis/chassis/Power",
    "/redfish/v1/Chassis/chassis/Thermal",
    "/redfish/v1/Systems/system/LogServices/EventLog/Entries",
]


@pytest.mark.tc(
    id="TC01",
    objective="Redfish service root is accessible.",
    preconditions=["Mock Redfish server running", "Scenario A (normal)"],
    steps=["GET /redfish/v1/ via RedfishClient.get_service_root()",
           "Check RedfishVersion, @odata.id and Systems/Chassis links"],
    expected="HTTP 200 with a JSON ServiceRoot containing RedfishVersion and links to Systems and Chassis.",
)
@pytest.mark.scenario("normal")
def test_tc01_service_root_accessible(redfish_client: RedfishClient, evidence) -> None:
    root = redfish_client.get_service_root()

    evidence.record(
        f"RedfishVersion={root.get('RedfishVersion')}, @odata.id={root.get('@odata.id')}, "
        f"Systems={root.get('Systems')}, Chassis={root.get('Chassis')}",
        product=root.get("Product"),
    )
    assert root["@odata.id"] == "/redfish/v1/"
    assert root["RedfishVersion"]
    assert RedfishClient.link(root, "Systems") == "/redfish/v1/Systems"
    assert RedfishClient.link(root, "Chassis") == "/redfish/v1/Chassis"


@pytest.mark.tc(
    id="SUP-RF-01",
    objective="Every minimum mock endpoint returns a Redfish JSON object with @odata.id.",
    preconditions=["Mock Redfish server running", "Valid credentials"],
    steps=["GET each minimum endpoint", "Check JSON object and @odata.id"],
    expected="HTTP 200 JSON object whose @odata.id matches the requested URI.",
)
@pytest.mark.scenario("normal")
@pytest.mark.parametrize("uri", MINIMUM_ENDPOINTS)
def test_minimum_endpoints_return_redfish_json(redfish_client: RedfishClient, uri: str, evidence) -> None:
    body = redfish_client.get(uri)
    evidence.record(f"GET {uri} -> @odata.id={body.get('@odata.id')}")
    assert body["@odata.id"] == uri


@pytest.mark.tc(
    id="SUP-RF-02",
    objective="Resources are discovered from links, not hardcoded IDs.",
    preconditions=["Scenario vendor_ids (Systems/Self, Chassis/1)"],
    steps=["Discover system/chassis URIs from the service root",
           "Fetch Power, Thermal and event log through discovered links",
           "Confirm the OpenBMC-style hardcoded URI is absent"],
    expected="Discovered URIs are /Systems/Self and /Chassis/1; resources load; /Systems/system returns 404.",
)
@pytest.mark.scenario("vendor_ids")
def test_resource_discovery_with_vendor_ids(redfish_client: RedfishClient, evidence) -> None:
    system_uri, chassis_uri = redfish_client.system_uri(), redfish_client.chassis_uri()
    power, thermal = redfish_client.get_power(), redfish_client.get_thermal()
    logs = redfish_client.get_event_logs()
    evidence.record(f"system={system_uri}, chassis={chassis_uri}, power={power['@odata.id']}, "
                    f"thermal={thermal['@odata.id']}, log_entries={len(logs)}")

    assert system_uri == "/redfish/v1/Systems/Self"
    assert chassis_uri == "/redfish/v1/Chassis/1"
    assert power["@odata.id"] == "/redfish/v1/Chassis/1/Power"
    assert thermal["Temperatures"] and thermal["Fans"]
    assert logs and all(e.get("EntryType") == "Event" for e in logs)
    with pytest.raises(RedfishHTTPError) as exc:
        redfish_client.get("/redfish/v1/Systems/system")
    assert exc.value.status_code == 404


@pytest.mark.tc(
    id="SUP-RF-03",
    objective="Authentication failures are reported as RedfishAuthError.",
    preconditions=["Mock enforces Basic auth"],
    steps=["Call get_system() with a wrong password", "Call get_system() with no credentials"],
    expected="Both raise RedfishAuthError (HTTP 401); the public service root stays reachable.",
)
@pytest.mark.parametrize("password", ["wrong-password", None], ids=["wrong_password", "no_credentials"])
def test_authentication_failure(mock_server, password: str | None, evidence) -> None:
    client = RedfishClient(RedfishConfig(mock_server.base_url, username=mock_server.username if password else None,
                                         password=password))
    assert client.get_service_root()["RedfishVersion"]
    with pytest.raises(RedfishAuthError) as exc:
        client.get_system()
    evidence.record(f"RedfishAuthError: {exc.value}")
    assert "401" in str(exc.value)


@pytest.mark.tc(
    id="SUP-RF-04",
    objective="A BMC-side service failure (HTTP 503) is reported with the Redfish error message.",
    preconditions=["Mock fault injection: 503"],
    steps=["Inject 503 fault via /mock/fault", "Call get_service_root()"],
    expected="RedfishHTTPError with status_code 503 and the Redfish error.message text.",
)
def test_bmc_service_error_is_parsed(mock_server, redfish_client: RedfishClient, evidence) -> None:
    mock_server.inject_fault(503, "Simulated BMC web service overload.")
    with pytest.raises(RedfishHTTPError) as exc:
        redfish_client.get_service_root()
    evidence.record(f"status={exc.value.status_code}, message={exc.value.redfish_message!r}")
    assert exc.value.status_code == 503
    assert exc.value.redfish_message == "Simulated BMC web service overload."


@pytest.mark.tc(
    id="SUP-RF-05",
    objective="An unreachable BMC raises RedfishConnectionError instead of hanging or crashing.",
    preconditions=["Nothing listening on the target port"],
    steps=["Create a client for an unused loopback port", "Call get_service_root()"],
    expected="RedfishConnectionError within the configured timeout.",
)
def test_unreachable_bmc(unreachable_base_url: str, evidence) -> None:
    client = RedfishClient(RedfishConfig(unreachable_base_url, timeout=2))
    with pytest.raises(RedfishConnectionError) as exc:
        client.get_service_root()
    evidence.record(f"RedfishConnectionError raised: {type(exc.value).__name__}")


@pytest.mark.tc(
    id="SUP-RF-06",
    objective="Credentials never appear in logs or object representations.",
    preconditions=["Mock Redfish server running"],
    steps=["Perform several authenticated requests with INFO logging", "Inspect log text and repr(config)"],
    expected="The password string appears in neither the captured logs nor repr(config).",
)
def test_password_not_exposed(redfish_client: RedfishClient, redfish_config: RedfishConfig, caplog, evidence) -> None:
    caplog.set_level(logging.DEBUG)
    redfish_client.get_system()
    redfish_client.get_thermal()
    evidence.record(f"captured {len(caplog.records)} log records; repr={redfish_config!r}")
    assert redfish_config.password and redfish_config.password not in caplog.text
    assert redfish_config.password not in repr(redfish_config)
