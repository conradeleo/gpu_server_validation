"""Reusable, read-only Redfish client.

Design notes:
* Resource URIs are discovered from ``@odata.id`` links (service root -> collections ->
  members) instead of being hardcoded, because BMC vendors use different IDs
  (``Systems/system`` on OpenBMC, ``Systems/Self``, ``Systems/1``, ...).
* Only GET is implemented. The framework never changes BMC state.
* Credentials come from the caller or environment variables and are never logged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

SERVICE_ROOT = "/redfish/v1/"


# ----------------------------------------------------------------------------- errors
class RedfishError(Exception):
    """Base class for all Redfish client errors."""


class RedfishConnectionError(RedfishError):
    """The BMC could not be reached (DNS, refused connection, timeout, TLS failure)."""


class RedfishAuthError(RedfishError):
    """The BMC rejected the credentials (HTTP 401/403)."""


class RedfishHTTPError(RedfishError):
    """The BMC returned a non-success HTTP status."""

    def __init__(self, status_code: int, uri: str, message: str):
        super().__init__(f"HTTP {status_code} for {uri}: {message}")
        self.status_code = status_code
        self.uri = uri
        self.redfish_message = message


class RedfishResponseError(RedfishError):
    """The response body was not valid Redfish JSON or lacked a required link/field."""


# ----------------------------------------------------------------------------- config
def _env_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RedfishConfig:
    """Connection settings. ``password`` is excluded from ``repr`` to keep it out of logs."""

    base_url: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    verify_tls: bool = True
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https://, got {self.base_url!r}")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def from_env(cls, defaults: dict[str, Any] | None = None) -> "RedfishConfig":
        """Build from ``REDFISH_*`` environment variables, falling back to ``defaults``
        (typically the ``redfish`` section of ``config/test_config.yaml``)."""
        d = defaults or {}
        return cls(
            base_url=os.getenv("REDFISH_BASE_URL") or d.get("base_url", "http://127.0.0.1:8000"),
            username=os.getenv("REDFISH_USERNAME") or None,
            password=os.getenv("REDFISH_PASSWORD") or None,
            verify_tls=_env_bool(os.getenv("REDFISH_VERIFY_TLS"), bool(d.get("verify_tls", True))),
            timeout=float(os.getenv("REDFISH_TIMEOUT") or d.get("timeout_seconds", 5)),
        )


# ----------------------------------------------------------------------------- client
class RedfishClient:
    """Read-only Redfish client with link-based resource discovery."""

    def __init__(self, config: RedfishConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "OData-Version": "4.0"})
        if config.username and config.password:
            self.session.auth = (config.username, config.password)
        self.session.verify = config.verify_tls
        if not config.verify_tls:
            logger.warning("TLS verification is DISABLED for %s", config.base_url)

    # ------------------------------------------------------------------ low level
    def get(self, uri: str) -> dict[str, Any]:
        """GET ``uri`` (absolute path such as ``/redfish/v1/Systems``) and return the JSON object.

        Raises:
            RedfishConnectionError, RedfishAuthError, RedfishHTTPError, RedfishResponseError
        """
        if not uri.startswith("/"):
            raise ValueError(f"uri must be an absolute path, got {uri!r}")
        url = self.config.base_url + uri
        try:
            resp = self.session.get(url, timeout=self.config.timeout)
        except requests.exceptions.Timeout as exc:
            raise RedfishConnectionError(f"Timeout after {self.config.timeout}s: GET {uri}") from exc
        except requests.exceptions.SSLError as exc:
            raise RedfishConnectionError(f"TLS error for GET {uri}: {exc}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(f"Cannot connect to {self.config.base_url}: {exc}") from exc

        logger.info("GET %s -> %d (%.0f ms)", uri, resp.status_code, resp.elapsed.total_seconds() * 1000)

        if resp.status_code in (401, 403):
            raise RedfishAuthError(f"HTTP {resp.status_code} for {uri}: {self._error_message(resp)}")
        if not resp.ok:
            raise RedfishHTTPError(resp.status_code, uri, self._error_message(resp))
        try:
            data = resp.json()
        except ValueError as exc:
            raise RedfishResponseError(f"Response for {uri} is not valid JSON") from exc
        if not isinstance(data, dict):
            raise RedfishResponseError(f"Response for {uri} is not a JSON object")
        return data

    @staticmethod
    def _error_message(resp: requests.Response) -> str:
        """Extract the Redfish ``error.message`` if present, else a short body excerpt."""
        try:
            body = resp.json()
            err = body.get("error", {}) if isinstance(body, dict) else {}
            msg = err.get("message")
            if msg:
                return str(msg)
        except ValueError:
            pass
        return (resp.text or resp.reason or "").strip()[:200]

    @staticmethod
    def link(resource: dict[str, Any], *path: str) -> str:
        """Follow nested keys to an ``@odata.id`` link, e.g. ``link(root, "Systems")``."""
        node: Any = resource
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise RedfishResponseError(
                    f"Missing link {'/'.join(path)} in {resource.get('@odata.id', '<resource>')}"
                )
            node = node[key]
        if not isinstance(node, dict) or not isinstance(node.get("@odata.id"), str):
            raise RedfishResponseError(f"Link {'/'.join(path)} has no @odata.id")
        return node["@odata.id"]

    def members(self, collection_uri: str) -> list[str]:
        """Return member URIs of a Redfish collection."""
        coll = self.get(collection_uri)
        members = coll.get("Members")
        if not isinstance(members, list):
            raise RedfishResponseError(f"Collection {collection_uri} has no Members array")
        uris = [m["@odata.id"] for m in members if isinstance(m, dict) and "@odata.id" in m]
        if not uris:
            raise RedfishResponseError(f"Collection {collection_uri} is empty")
        return uris

    # ------------------------------------------------------------------ discovery
    def get_service_root(self) -> dict[str, Any]:
        root = self.get(SERVICE_ROOT)
        if "RedfishVersion" not in root:
            raise RedfishResponseError("Service root lacks RedfishVersion")
        return root

    def system_uri(self) -> str:
        """URI of the first ComputerSystem (single-node servers expose exactly one)."""
        return self.members(self.link(self.get_service_root(), "Systems"))[0]

    def chassis_uri(self) -> str:
        """URI of the first Chassis."""
        return self.members(self.link(self.get_service_root(), "Chassis"))[0]

    # ------------------------------------------------------------------ resources
    def get_system(self) -> dict[str, Any]:
        return self.get(self.system_uri())

    def get_chassis(self) -> dict[str, Any]:
        return self.get(self.chassis_uri())

    def get_power(self) -> dict[str, Any]:
        """Legacy ``Power`` resource of the first chassis.

        Newer BMCs may only offer ``PowerSubsystem``; that is not handled yet (Phase 2).
        """
        return self.get(self.link(self.get_chassis(), "Power"))

    def get_thermal(self) -> dict[str, Any]:
        """Legacy ``Thermal`` resource of the first chassis (``ThermalSubsystem`` not handled yet)."""
        return self.get(self.link(self.get_chassis(), "Thermal"))

    def get_event_logs(self) -> list[dict[str, Any]]:
        """Return LogEntry objects from the system's event log service.

        Prefers a LogService with Id ``EventLog`` (OpenBMC); otherwise uses the first one.
        Members returned only as links are fetched individually.
        """
        services_uri = self.link(self.get_system(), "LogServices")
        service_uris = self.members(services_uri)
        chosen = next((u for u in service_uris if u.rstrip("/").endswith("/EventLog")), service_uris[0])
        entries = self.get(self.link(self.get(chosen), "Entries"))
        result: list[dict[str, Any]] = []
        for m in entries.get("Members", []):
            if isinstance(m, dict) and set(m) == {"@odata.id"}:
                m = self.get(m["@odata.id"])
            if isinstance(m, dict):
                result.append(m)
        return result
