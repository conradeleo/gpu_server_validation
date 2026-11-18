"""Local mock Redfish API server (FastAPI). ALL DATA IS SIMULATED.

Serves representative Redfish resources for the active scenario defined in
``config/mock_scenarios.yaml``. Scenario selection (highest priority first):

1. ``--scenario`` command-line option
2. ``MOCK_SCENARIO`` environment variable
3. ``mock.default_scenario`` in ``config/test_config.yaml``

At runtime the scenario can be switched with ``PUT /mock/scenario`` and a BMC-side
service failure can be injected with ``PUT /mock/fault``. The ``/mock/*`` control
endpoints are NOT part of Redfish and exist only for test orchestration.

Run:  python -m mocks.mock_redfish_server --scenario normal --port 8000
"""

from __future__ import annotations

import argparse
import base64
import binascii
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from common.config import load_test_config, resolve_path
from mocks import redfish_payloads as rp
from mocks.scenarios import load_scenarios

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/redfish", "/redfish/", "/redfish/v1", "/redfish/v1/"}


class RedfishErrorResponse(Exception):
    """Raised inside handlers to return a Redfish-formatted error."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


@dataclass
class MockState:
    """Mutable server state: loaded scenarios, active scenario, injected fault, credentials."""

    scenarios: dict[str, dict[str, Any]]
    active: str
    username: str | None = None
    password: str | None = None
    fault: dict[str, Any] | None = None
    request_log: list[str] = field(default_factory=list)

    @property
    def scenario(self) -> dict[str, Any]:
        return self.scenarios[self.active]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.username and self.password)


class ScenarioRequest(BaseModel):
    name: str


class FaultRequest(BaseModel):
    status_code: int = Field(ge=400, le=599)
    message: str = "Simulated BMC service failure."


def _check_basic_auth(request: Request, state: MockState) -> None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            user, pwd = "", ""
        if secrets.compare_digest(user, state.username or "") and secrets.compare_digest(
            pwd, state.password or ""
        ):
            return
    raise RedfishErrorResponse(
        401,
        "InsufficientPrivilege",
        "Authentication is required or the supplied credentials are invalid.",
        headers={"WWW-Authenticate": 'Basic realm="Redfish"'},
    )


def create_app(
    scenario_file: str | Path = "config/mock_scenarios.yaml",
    scenario: str = "normal",
    username: str | None = None,
    password: str | None = None,
) -> FastAPI:
    """Build the mock Redfish FastAPI application.

    Args:
        scenario_file: YAML file with scenario definitions.
        scenario: initial active scenario name.
        username/password: if both are given, HTTP Basic auth is enforced on
            every Redfish resource except the service root.
    """
    scenarios = load_scenarios(resolve_path(scenario_file))
    if scenario not in scenarios:
        raise ValueError(f"Unknown scenario '{scenario}'. Available: {sorted(scenarios)}")
    state = MockState(scenarios=scenarios, active=scenario, username=username, password=password)

    app = FastAPI(title="Mock Redfish Service (SIMULATED)", docs_url="/mock/docs", redoc_url=None)
    app.state.mock = state

    @app.exception_handler(RedfishErrorResponse)
    async def _redfish_error(_: Request, exc: RedfishErrorResponse) -> JSONResponse:
        return JSONResponse(rp.redfish_error(exc.code, exc.message), exc.status_code, headers=exc.headers)

    @app.middleware("http")
    async def _guard(request: Request, call_next: Callable) -> Any:
        path = request.url.path
        if path.startswith("/redfish"):
            state.request_log.append(f"{request.method} {path}")
            if state.fault:
                return JSONResponse(
                    rp.redfish_error("GeneralError", state.fault["message"]),
                    state.fault["status_code"],
                    headers={"OData-Version": "4.0"},
                )
            if state.auth_enabled and path not in PUBLIC_PATHS:
                try:
                    _check_basic_auth(request, state)
                except RedfishErrorResponse as exc:
                    return await _redfish_error(request, exc)
        response = await call_next(request)
        if path.startswith("/redfish"):
            response.headers["OData-Version"] = "4.0"
        return response

    def ids() -> dict[str, str]:
        return state.scenario["resource_ids"]

    def require(actual: str, expected: str, uri: str) -> None:
        if actual != expected:
            raise RedfishErrorResponse(404, "ResourceNotFound", f"The requested resource {uri} was not found.")

    # ---------------- Redfish resources ----------------
    @app.get("/redfish")
    def versions() -> dict[str, str]:
        return {"v1": "/redfish/v1/"}

    @app.get("/redfish/v1")
    @app.get("/redfish/v1/")
    def service_root() -> dict[str, Any]:
        return rp.service_root(state.scenario)

    @app.get("/redfish/v1/Systems")
    def systems() -> dict[str, Any]:
        return rp.collection("Systems", "ComputerSystemCollection.ComputerSystemCollection", [ids()["system"]])

    @app.get("/redfish/v1/Chassis")
    def chassis_collection() -> dict[str, Any]:
        return rp.collection("Chassis", "ChassisCollection.ChassisCollection", [ids()["chassis"]])

    @app.get("/redfish/v1/Managers")
    def managers() -> dict[str, Any]:
        return rp.collection("Managers", "ManagerCollection.ManagerCollection", ["bmc"])

    @app.get("/redfish/v1/Systems/{system_id}")
    def system(system_id: str, request: Request) -> dict[str, Any]:
        require(system_id, ids()["system"], request.url.path)
        return rp.computer_system(state.scenario)

    @app.get("/redfish/v1/Systems/{system_id}/LogServices")
    def log_services(system_id: str, request: Request) -> dict[str, Any]:
        require(system_id, ids()["system"], request.url.path)
        return rp.log_services(state.scenario)

    @app.get("/redfish/v1/Systems/{system_id}/LogServices/EventLog")
    def event_log_service(system_id: str, request: Request) -> dict[str, Any]:
        require(system_id, ids()["system"], request.url.path)
        return rp.event_log_service(state.scenario)

    @app.get("/redfish/v1/Systems/{system_id}/LogServices/EventLog/Entries")
    def event_log_entries(system_id: str, request: Request) -> dict[str, Any]:
        require(system_id, ids()["system"], request.url.path)
        return rp.log_entries(state.scenario)

    @app.get("/redfish/v1/Systems/{system_id}/LogServices/EventLog/Entries/{entry_id}")
    def event_log_entry(system_id: str, entry_id: str, request: Request) -> dict[str, Any]:
        require(system_id, ids()["system"], request.url.path)
        for ev in state.scenario["events"]:
            if str(ev["id"]) == entry_id:
                return rp.log_entry(state.scenario, ev)
        raise RedfishErrorResponse(404, "ResourceNotFound", f"The requested resource {request.url.path} was not found.")

    @app.get("/redfish/v1/Chassis/{chassis_id}")
    def chassis(chassis_id: str, request: Request) -> dict[str, Any]:
        require(chassis_id, ids()["chassis"], request.url.path)
        return rp.chassis(state.scenario)

    @app.get("/redfish/v1/Chassis/{chassis_id}/Power")
    def power(chassis_id: str, request: Request) -> dict[str, Any]:
        require(chassis_id, ids()["chassis"], request.url.path)
        return rp.power(state.scenario)

    @app.get("/redfish/v1/Chassis/{chassis_id}/Thermal")
    def thermal(chassis_id: str, request: Request) -> dict[str, Any]:
        require(chassis_id, ids()["chassis"], request.url.path)
        return rp.thermal(state.scenario)

    @app.api_route("/redfish/{rest:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    def not_found(rest: str, request: Request) -> None:
        raise RedfishErrorResponse(404, "ResourceNotFound", f"The requested resource {request.url.path} was not found.")

    # ---------------- Mock control endpoints (not Redfish) ----------------
    @app.get("/mock/scenarios")
    def list_scenarios() -> dict[str, Any]:
        return {
            "active": state.active,
            "scenarios": {n: s.get("description", "") for n, s in state.scenarios.items()},
        }

    @app.get("/mock/scenario")
    def get_scenario() -> dict[str, Any]:
        return {"active": state.active, "fault": state.fault, "host": state.scenario["host"]}

    @app.put("/mock/scenario")
    def set_scenario(req: ScenarioRequest) -> dict[str, Any]:
        if req.name not in state.scenarios:
            raise HTTPException(404, f"Unknown scenario '{req.name}'. Available: {sorted(state.scenarios)}")
        state.active = req.name
        logger.info("Mock scenario switched to %s", req.name)
        return {"active": state.active}

    @app.put("/mock/fault")
    def set_fault(req: FaultRequest) -> dict[str, Any]:
        state.fault = req.model_dump()
        logger.info("Mock fault injected: %s", state.fault)
        return {"fault": state.fault}

    @app.delete("/mock/fault")
    def clear_fault() -> dict[str, Any]:
        state.fault = None
        return {"fault": None}

    return app


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    import uvicorn

    cfg = load_test_config().get("mock", {})
    parser = argparse.ArgumentParser(description="Mock Redfish server (SIMULATED data).")
    parser.add_argument("--scenario", default=os.getenv("MOCK_SCENARIO") or cfg.get("default_scenario", "normal"))
    parser.add_argument("--scenario-file", default=cfg.get("scenario_file", "config/mock_scenarios.yaml"))
    parser.add_argument("--host", default=cfg.get("host", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8000)))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app(
        args.scenario_file,
        args.scenario,
        username=os.getenv("MOCK_REDFISH_USERNAME") or None,
        password=os.getenv("MOCK_REDFISH_PASSWORD") or None,
    )
    logger.info(
        "Starting mock Redfish on http://%s:%d (scenario=%s, auth=%s)",
        args.host, args.port, args.scenario, app.state.mock.auth_enabled,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
