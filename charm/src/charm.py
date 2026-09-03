#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd
# See LICENSE file for licensing details.

"""Landscape MCP server charm.

Runs the Landscape MCP server with the streamable HTTP transport in a
container and optionally publishes it through HAProxy via the
haproxy-route relation, so it can sit behind the same HAProxy as the
landscape-server charm.
"""

import logging
import typing

import ops
from charms.haproxy.v1.haproxy_route import HaproxyRouteRequirer

logger = logging.getLogger(__name__)

CONTAINER_NAME = "landscape-mcp"
MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"


class LandscapeMcpCharm(ops.CharmBase):
    """Charm for the Landscape MCP server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.haproxy_route = HaproxyRouteRequirer(
            self, relation_name="mcp-haproxy-route"
        )

        framework.observe(self.on["landscape-mcp"].pebble_ready, self._reconcile)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on["mcp-haproxy-route"].relation_joined, self._reconcile)
        framework.observe(
            self.on["mcp-haproxy-route"].relation_changed, self._reconcile
        )

    @property
    def port(self) -> int:
        """Port the MCP server listens on."""
        return typing.cast(int, self.config["port"])

    @property
    def unit_address(self) -> str | None:
        """Routable address of this unit for HAProxy backends."""
        binding = self.model.get_binding("mcp-haproxy-route")
        if binding is None:
            return None
        address = binding.network.bind_address
        return str(address) if address else None

    def _pebble_layer(self) -> ops.pebble.LayerDict:
        return {
            "summary": "Landscape MCP server",
            "description": "Pebble layer for the Landscape MCP server",
            "services": {
                "landscape-mcp": {
                    "override": "replace",
                    "summary": "Landscape MCP server (streamable HTTP)",
                    "command": (
                        "/usr/local/bin/landscape-mcp"
                        f" -transport http -addr :{self.port}"
                    ),
                    "startup": "enabled",
                    "environment": {
                        "LANDSCAPE_API_URI": str(self.config["landscape-api-uri"]),
                        "LANDSCAPE_API_KEY": str(self.config["landscape-api-key"]),
                        "LANDSCAPE_API_SECRET": str(
                            self.config["landscape-api-secret"]
                        ),
                    },
                }
            },
            "checks": {
                "up": {
                    "override": "replace",
                    "level": "alive",
                    "http": {"url": f"http://localhost:{self.port}{HEALTH_PATH}"},
                }
            },
        }

    def _reconcile(self, event: ops.EventBase) -> None:
        """Reconcile the workload and relation data with the current config."""
        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.defer()
            return

        if not self.config["landscape-api-key"]:
            self.unit.status = ops.BlockedStatus("Missing landscape-api-key config")
            return

        container.add_layer(CONTAINER_NAME, self._pebble_layer(), combine=True)
        container.replan()
        self._provide_haproxy_route()
        self.unit.status = ops.ActiveStatus()

    def _provide_haproxy_route(self) -> None:
        """Publish the MCP route to HAProxy when related."""
        if not self.model.get_relation("mcp-haproxy-route"):
            return
        if not self.unit.is_leader():
            return
        unit_address = self.unit_address
        if unit_address is None:
            logger.warning("No bind address for mcp-haproxy-route yet")
            return

        self.haproxy_route.provide_haproxy_route_requirements(
            service=f"landscape-mcp-{self.model.uuid}",
            ports=[self.port],
            paths=[MCP_PATH],
            protocol="http",
            check_path=HEALTH_PATH,
            check_interval=2,
            check_rise=2,
            check_fall=3,
            header_rewrite_expressions=[("X-Forwarded-Proto", "https")],
            unit_address=unit_address,
        )
        logger.info("Published haproxy route for %s on port %d", MCP_PATH, self.port)


if __name__ == "__main__":
    ops.main(LandscapeMcpCharm)
