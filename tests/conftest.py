"""Shared fixtures: an in-process mock Redfish server and Redfish clients.

The mock server runs on a real loopback socket (uvicorn in a background thread) so the
client is exercised over genuine HTTP. Tests never touch a real BMC or GPU.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests
import uvicorn

from bmc.redfish_client import RedfishClient, RedfishConfig
from common.config import load_test_config
from mocks.mock_redfish_server import create_app

DEFAULT_SCENARIO = "normal"


@dataclass
class MockServerHandle:
    """Handle to the running mock; exposes the /mock control API."""

    base_url: str
    username: str
    password: str = field(repr=False)
    app: Any = field(repr=False)

    def _control(self) -> requests.Session:
        s = requests.Session()
        s.trust_env = False  # never route loopback control calls through a proxy
        return s

    def set_scenario(self, name: str) -> None:
        r = self._control().put(f"{self.base_url}/mock/scenario", json={"name": name}, timeout=5)
        r.raise_for_status()

    def inject_fault(self, status_code: int, message: str = "Simulated BMC service failure.") -> None:
        r = self._control().put(
            f"{self.base_url}/mock/fault", json={"status_code": status_code, "message": message}, timeout=5
        )
        r.raise_for_status()

    def clear_fault(self) -> None:
        self._control().delete(f"{self.base_url}/mock/fault", timeout=5).raise_for_status()


@pytest.fixture(scope="session")
def test_config() -> dict[str, Any]:
    return load_test_config()


@pytest.fixture(scope="session")
def mock_server(test_config: dict[str, Any]) -> Iterator[MockServerHandle]:
    """Start the mock Redfish server with per-run random Basic-auth credentials."""
    for var in ("NO_PROXY", "no_proxy"):
        os.environ[var] = ",".join(filter(None, [os.environ.get(var), "127.0.0.1", "localhost"]))

    username, password = "validator", secrets.token_urlsafe(16)
    app = create_app(
        test_config["mock"]["scenario_file"], DEFAULT_SCENARIO, username=username, password=password
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("Mock Redfish server failed to start")
        time.sleep(0.02)

    yield MockServerHandle(f"http://127.0.0.1:{port}", username, password, app)

    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.fixture(autouse=True)
def _apply_scenario(request: pytest.FixtureRequest) -> None:
    """Reset the mock to the test's ``@pytest.mark.scenario`` (default: normal) and clear faults.

    Only applies to tests that use the mock; pure unit tests stay server-free.
    """
    marker = request.node.get_closest_marker("scenario")
    uses_mock = {"mock_server", "redfish_client", "redfish_config"} & set(request.fixturenames)
    if not marker and not uses_mock:
        return
    handle: MockServerHandle = request.getfixturevalue("mock_server")
    handle.clear_fault()
    handle.set_scenario(marker.args[0] if marker else DEFAULT_SCENARIO)


@pytest.fixture
def redfish_config(mock_server: MockServerHandle, test_config: dict[str, Any]) -> RedfishConfig:
    rf = test_config["redfish"]
    return RedfishConfig(
        base_url=mock_server.base_url,
        username=mock_server.username,
        password=mock_server.password,
        verify_tls=bool(rf.get("verify_tls", True)),
        timeout=float(rf.get("timeout_seconds", 5)),
    )


@pytest.fixture
def redfish_client(redfish_config: RedfishConfig) -> RedfishClient:
    return RedfishClient(redfish_config)


@pytest.fixture
def unreachable_base_url() -> str:
    """A loopback URL on a port that was free a moment ago (nothing listening)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"
