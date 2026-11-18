"""Quick read-only BMC check: ``python -m bmc``.

Reads REDFISH_* environment variables (see .env.example) and prints a JSON summary.
Exit code: 0 on success, 2 on any Redfish error.
"""

from __future__ import annotations

import json
import logging
import sys

from bmc.power_collector import collect_power_state
from bmc.redfish_client import RedfishClient, RedfishConfig, RedfishError
from common.config import load_test_config


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    config = RedfishConfig.from_env(load_test_config().get("redfish", {}))
    client = RedfishClient(config)
    try:
        root = client.get_service_root()
        summary = {
            "base_url": config.base_url,
            "redfish_version": root.get("RedfishVersion"),
            "product": root.get("Product"),
            "system_uri": client.system_uri(),
            "chassis_uri": client.chassis_uri(),
            "power": collect_power_state(client).as_dict(),
        }
    except RedfishError as exc:
        print(json.dumps({"base_url": config.base_url, "error": type(exc).__name__, "detail": str(exc)}, indent=2))
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
