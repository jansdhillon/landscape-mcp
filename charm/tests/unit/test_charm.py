# Copyright 2026 Canonical Ltd
# See LICENSE file for licensing details.

from types import SimpleNamespace

import pytest
from ops import testing

from charm import LandscapeMcpCharm

CHARM_META = {
    "name": "landscape-mcp",
    "containers": {"landscape-mcp": {}},
    "requires": {
        "mcp-haproxy-route": {"interface": "haproxy-route", "limit": 1},
        "certificates": {"interface": "tls-certificates", "limit": 1},
    },
    "provides": {"send-ca-cert": {"interface": "certificate_transfer"}},
}

CONFIG = {
    "options": {
        "landscape-api-uri": {
            "type": "string",
            "default": "https://landscape.canonical.com/api/",
        },
        "landscape-api-credentials": {"type": "secret"},
        "port": {"type": "int", "default": 8080},
    }
}


@pytest.fixture
def ctx():
    return testing.Context(LandscapeMcpCharm, meta=CHARM_META, config=CONFIG, unit_id=0)


def creds_secret(**content):
    return testing.Secret(
        tracked_content=content or {"api-key": "key", "api-secret": "secret"}
    )


def with_creds(secret=None):
    secret = secret or creds_secret()
    return secret, {"landscape-api-credentials": secret.id}


def container():
    return testing.Container("landscape-mcp", can_connect=True)


class TestReconcile:
    def test_blocked_without_credentials_config(self, ctx):
        state = testing.State(containers={container()}, leader=True)
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.BlockedStatus(
            "Missing landscape-api-credentials config"
        )

    def test_blocked_when_secret_not_granted(self, ctx):
        state = testing.State(
            containers={container()},
            leader=True,
            config={"landscape-api-credentials": "secret:cvbpf1l6n1jc7c1jkjg0"},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.BlockedStatus(
            "Credentials secret not found or not granted"
        )

    def test_blocked_when_secret_missing_fields(self, ctx):
        secret, cfg = with_creds(creds_secret(**{"api-key": "key"}))
        state = testing.State(
            containers={container()}, leader=True, secrets={secret}, config=cfg
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.BlockedStatus(
            "Credentials secret missing fields: api-secret"
        )

    def test_secret_changed_updates_environment(self, ctx):
        secret, cfg = with_creds()
        state = testing.State(
            containers={container()}, leader=True, secrets={secret}, config=cfg
        )
        out = ctx.run(ctx.on.config_changed(), state)
        new_secret = testing.Secret(
            id=secret.id,
            tracked_content={"api-key": "key", "api-secret": "secret"},
            latest_content={"api-key": "key2", "api-secret": "secret2"},
        )
        state = testing.State(
            containers=out.containers, leader=True, secrets={new_secret}, config=cfg
        )
        out = ctx.run(ctx.on.secret_changed(new_secret), state)
        env = (
            out.get_container("landscape-mcp")
            .layers["landscape-mcp"]
            .services["landscape-mcp"]
            .environment
        )
        assert env["LANDSCAPE_API_KEY"] == "key2"
        assert env["LANDSCAPE_API_SECRET"] == "secret2"

    def test_active_with_config(self, ctx):
        secret, cfg = with_creds()
        state = testing.State(
            containers={container()},
            leader=True,
            secrets={secret},
            config=cfg,
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
        secret, cfg = with_creds()
        state = testing.State(
            containers={testing.Container("landscape-mcp", can_connect=False)},
            leader=True,
            secrets={secret},
            config=cfg,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert len(out.deferred) == 1

    def test_custom_port_in_command_and_check(self, ctx):
        secret, cfg = with_creds()
        state = testing.State(
            containers={container()},
            leader=True,
            secrets={secret},
            config={**cfg, "port": 9090},
        )
        out = ctx.run(ctx.on.config_changed(), state)
        layer = out.get_container("landscape-mcp").layers["landscape-mcp"]
        assert "-addr :9090" in layer.services["landscape-mcp"].command
        assert layer.checks["up"].http["url"] == "http://localhost:9090/healthz"


class TestHaproxyRoute:
    def test_publishes_route_when_related(self, ctx):
        secret, cfg = with_creds()
        relation = testing.Relation("mcp-haproxy-route")
        state = testing.State(
            containers={container()},
            leader=True,
            relations={relation},
            secrets={secret},
            config=cfg,
        )
        out = ctx.run(ctx.on.relation_joined(relation), state)
        assert out.unit_status == testing.ActiveStatus()

        rel = out.get_relation(relation.id)
        app_data = rel.local_app_data
        assert "services" in app_data or "service" in app_data

    def test_no_route_data_without_relation(self, ctx):
        secret, cfg = with_creds()
        state = testing.State(
            containers={container()},
            leader=True,
            secrets={secret},
            config=cfg,
        )
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.ActiveStatus()

    def test_non_leader_does_not_publish(self, ctx):
        secret, cfg = with_creds()
        relation = testing.Relation("mcp-haproxy-route")
        state = testing.State(
            containers={container()},
            leader=False,
            relations={relation},
            secrets={secret},
            config=cfg,
        )
        out = ctx.run(ctx.on.relation_joined(relation), state)
        assert out.unit_status == testing.ActiveStatus()
        rel = out.get_relation(relation.id)
        assert rel.local_app_data == {}


def issued(monkeypatch, assigned=True):
    """Fake the certificate the provider issued."""
    result = (
        (SimpleNamespace(certificate="CERT", ca="CA"), "KEY")
        if assigned
        else (None, None)
    )
    monkeypatch.setattr(
        "charm.TLSCertificatesRequiresV4.get_assigned_certificate",
        lambda self, certificate_request: result,
    )


class TestTls:
    def _state(self, **kwargs):
        secret, cfg = with_creds()
        relation = testing.Relation("certificates")
        state = testing.State(
            containers={container()},
            leader=kwargs.pop("leader", True),
            relations={relation, *kwargs.pop("relations", set())},
            secrets={secret},
            config=cfg,
            **kwargs,
        )
        return state, relation

    def test_serves_tls_with_issued_certificate(self, ctx, monkeypatch):
        issued(monkeypatch)
        state, _ = self._state()
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.ActiveStatus()

        c = out.get_container("landscape-mcp")
        svc = c.layers["landscape-mcp"].services["landscape-mcp"]
        assert (
            svc.environment["LANDSCAPE_MCP_TLS_CERT"]
            == "/etc/landscape-mcp/tls/server.crt"
        )
        assert (
            svc.environment["LANDSCAPE_MCP_TLS_KEY"]
            == "/etc/landscape-mcp/tls/server.key"
        )
        assert c.layers["landscape-mcp"].checks["up"].tcp == {"port": 8080}
        fs = c.get_filesystem(ctx)
        assert (fs / "etc/landscape-mcp/tls/server.crt").read_text() == "CERT"
        assert (fs / "etc/landscape-mcp/tls/server.key").read_text() == "KEY"

    def test_waits_for_certificate(self, ctx, monkeypatch):
        issued(monkeypatch, assigned=False)
        state, _ = self._state()
        out = ctx.run(ctx.on.config_changed(), state)
        assert out.unit_status == testing.WaitingStatus("Waiting for TLS certificate")
        assert "landscape-mcp" not in out.get_container("landscape-mcp").layers

    def test_no_tls_without_relation(self, ctx):
        secret, cfg = with_creds()
        state = testing.State(
            containers={container()}, leader=True, secrets={secret}, config=cfg
        )
        out = ctx.run(ctx.on.config_changed(), state)
        svc = (
            out.get_container("landscape-mcp")
            .layers["landscape-mcp"]
            .services["landscape-mcp"]
        )
        assert "LANDSCAPE_MCP_TLS_CERT" not in svc.environment
        layer = out.get_container("landscape-mcp").layers["landscape-mcp"]
        assert layer.checks["up"].http["url"] == "http://localhost:8080/healthz"

    def test_leader_sends_ca(self, ctx, monkeypatch):
        issued(monkeypatch)
        ca_relation = testing.Relation("send-ca-cert", remote_app_data={"version": "1"})
        state, _ = self._state(relations={ca_relation})
        out = ctx.run(ctx.on.relation_joined(ca_relation), state)
        data = out.get_relation(ca_relation.id).local_app_data
        assert "CA" in data["certificates"]

    def test_non_leader_does_not_send_ca(self, ctx, monkeypatch):
        issued(monkeypatch)
        ca_relation = testing.Relation("send-ca-cert")
        state, _ = self._state(relations={ca_relation}, leader=False)
        out = ctx.run(ctx.on.relation_joined(ca_relation), state)
        assert out.get_relation(ca_relation.id).local_app_data == {}

    def test_route_uses_https_when_tls_active(self, ctx, monkeypatch):
        issued(monkeypatch)
        route = testing.Relation("mcp-haproxy-route")
        state, _ = self._state(relations={route})
        out = ctx.run(ctx.on.relation_joined(route), state)
        data = out.get_relation(route.id).local_app_data
        assert data["protocol"] == '"https"'

    def test_route_uses_http_without_tls(self, ctx):
        secret, cfg = with_creds()
        route = testing.Relation("mcp-haproxy-route")
        state = testing.State(
            containers={container()},
            leader=True,
            relations={route},
            secrets={secret},
            config=cfg,
        )
        out = ctx.run(ctx.on.relation_joined(route), state)
        data = out.get_relation(route.id).local_app_data
        assert data.get("protocol", '"http"') == '"http"'
