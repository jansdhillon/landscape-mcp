# Copyright 2026 Canonical Ltd
# See LICENSE file for licensing details.

import pytest
from ops import testing

from charm import LandscapeMcpCharm

CHARM_META = {
    "name": "landscape-mcp",
    "containers": {"landscape-mcp": {}},
    "requires": {"mcp-haproxy-route": {"interface": "haproxy-route", "limit": 1}},
}

CONFIG = {
    "options": {
        "landscape-api-uri": {
            "type": "string",
            "default": "https://landscape.canonical.com/api/",
        },
        "landscape-api-key": {"type": "string", "default": ""},
        "landscape-api-secret": {"type": "string", "default": ""},
        "port": {"type": "int", "default": 8080},
    }
}


@pytest.fixture
def ctx():
    return testing.Context(LandscapeMcpCharm, meta=CHARM_META, config=CONFIG, unit_id=0)


def container():
    return testing.Container("landscape-mcp", can_connect=True)


class TestReconcile:
    def test_blocked_without_api_key(self, ctx):
        state = testing.State(containers={container()}, leader=True)
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.BlockedStatus(
            "Missing landscape-api-key config"
        )

    def test_active_with_config(self, ctx):
        state = testing.State(
            containers={container()},
            leader=True,
            config={
                "landscape-api-key": "key",
                "landscape-api-secret": "secret",
            },
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.ActiveStatus()

        service = out.get_container("landscape-mcp").services["landscape-mcp"]
        assert service.is_running()
        layer = out.get_container("landscape-mcp").layers["landscape-mcp"]
        svc = layer.services["landscape-mcp"]
        assert "-transport http" in svc.command
        assert "-addr :8080" in svc.command
        assert svc.environment["LANDSCAPE_API_KEY"] == "key"
        assert svc.environment["LANDSCAPE_API_SECRET"] == "secret"
        assert (
            svc.environment["LANDSCAPE_API_URI"]
            == "https://landscape.canonical.com/api/"
        )

    def test_defers_when_container_not_ready(self, ctx):
        state = testing.State(
            containers={testing.Container("landscape-mcp", can_connect=False)},
            leader=True,
            config={"landscape-api-key": "key"},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert len(out.deferred) == 1

    def test_custom_port_in_command_and_check(self, ctx):
        state = testing.State(
            containers={container()},
            leader=True,
            config={"landscape-api-key": "key", "port": 9090},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        layer = out.get_container("landscape-mcp").layers["landscape-mcp"]
        assert "-addr :9090" in layer.services["landscape-mcp"].command
        assert layer.checks["up"].http["url"] == "http://localhost:9090/healthz"


class TestHaproxyRoute:
    def test_publishes_route_when_related(self, ctx):
        relation = testing.Relation("mcp-haproxy-route")
        state = testing.State(
            containers={container()},
            leader=True,
            relations={relation},
            config={"landscape-api-key": "key"},
        )
        out = ctx.run(ctx.on.relation_joined(relation), state)
        assert out.unit_status == testing.ActiveStatus()

        rel = out.get_relation(relation.id)
        app_data = rel.local_app_data
        assert "services" in app_data or "service" in app_data

    def test_no_route_data_without_relation(self, ctx):
        state = testing.State(
            containers={container()},
            leader=True,
            config={"landscape-api-key": "key"},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.ActiveStatus()

    def test_non_leader_does_not_publish(self, ctx):
        relation = testing.Relation("mcp-haproxy-route")
        state = testing.State(
            containers={container()},
            leader=False,
            relations={relation},
            config={"landscape-api-key": "key"},
        )
        out = ctx.run(ctx.on.relation_joined(relation), state)
        assert out.unit_status == testing.ActiveStatus()
        rel = out.get_relation(relation.id)
        assert rel.local_app_data == {}
