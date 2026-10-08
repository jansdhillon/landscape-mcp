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
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferProvides,
)
from charms.haproxy.v1.haproxy_route import HaproxyRouteRequirer
from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateRequestAttributes,
    Mode,
    PrivateKey,
    ProviderCertificate,
    TLSCertificatesRequiresV4,
)

logger = logging.getLogger(__name__)

CONTAINER_NAME = "landscape-mcp"
MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"
SECRET_FIELDS = ("api-key", "api-secret")
TLS_DIR = "/etc/landscape-mcp/tls"
TLS_CERT_PATH = f"{TLS_DIR}/server.crt"
TLS_KEY_PATH = f"{TLS_DIR}/server.key"


class CredentialsError(Exception):
    """The Landscape API credentials secret is unusable."""


class LandscapeMcpCharm(ops.CharmBase):
    """Charm for the Landscape MCP server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.haproxy_route = HaproxyRouteRequirer(
            self, relation_name="mcp-haproxy-route"
        )

        self.certificates = TLSCertificatesRequiresV4(
            self,
            relationship_name="certificates",
            certificate_requests=[self._certificate_request()],
            mode=Mode.UNIT,
            refresh_events=[self.on.config_changed],
        )
        self.ca_transfer = CertificateTransferProvides(self, "send-ca-cert")

        framework.observe(self.on["landscape-mcp"].pebble_ready, self._reconcile)
        framework.observe(self.certificates.on.certificate_available, self._reconcile)
        framework.observe(self.on["certificates"].relation_broken, self._reconcile)
        framework.observe(self.on["send-ca-cert"].relation_joined, self._reconcile)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on.secret_changed, self._reconcile)
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

    def _certificate_request(self) -> CertificateRequestAttributes:
        """Request a certificate valid for the names and address HAProxy may use."""
        service_dns = f"{self.app.name}.{self.model.name}.svc.cluster.local"
        sans_dns = {
            service_dns,
            f"{self.unit.name.replace('/', '-')}.{self.app.name}-endpoints."
            f"{self.model.name}.svc.cluster.local",
        }
        hostname = str(self.config.get("external-hostname") or "")
        if hostname:
            sans_dns.add(hostname)
        address = self.unit_address
        return CertificateRequestAttributes(
            common_name=service_dns,
            sans_dns=sans_dns,
            sans_ip={address} if address else None,
        )

    def _tls_related(self) -> bool:
        relation = self.model.get_relation("certificates")
        return relation is not None and relation.active

    def _assigned_certificate(self) -> tuple[ProviderCertificate, PrivateKey] | None:
        """Return the issued certificate and its private key, if both exist."""
        certificate, key = self.certificates.get_assigned_certificate(
            certificate_request=self._certificate_request()
        )
        if certificate is None or key is None:
            return None
        return certificate, key

    def _push_tls_files(
        self,
        container: ops.Container,
        certificate: ProviderCertificate,
        key: PrivateKey,
    ) -> bool:
        """Write the certificate and key into the container; True if either changed."""
        wanted = {
            TLS_CERT_PATH: str(certificate.certificate),
            TLS_KEY_PATH: str(key),
        }
        changed = False
        for path, content in wanted.items():
            if container.exists(path) and container.pull(path).read() == content:
                continue
            container.push(
                path,
                content,
                make_dirs=True,
                permissions=0o600 if path == TLS_KEY_PATH else 0o644,
            )
            changed = True
        return changed

    def _credentials(self) -> dict[str, str]:
        """Read the API credentials from the configured Juju secret.

        Raises:
            CredentialsError: If the secret is unset, unreadable or incomplete.
        """
        secret_id = self.config.get("landscape-api-credentials")
        if not secret_id:
            raise CredentialsError("Missing landscape-api-credentials config")
        try:
            secret = self.model.get_secret(id=str(secret_id))
            content = secret.get_content(refresh=True)
        except ops.SecretNotFoundError:
            raise CredentialsError(
                "Credentials secret not found or not granted"
            ) from None
        except ops.ModelError as e:
            raise CredentialsError(f"Cannot read credentials secret: {e}") from None
        missing = [f for f in SECRET_FIELDS if not content.get(f)]
        if missing:
            raise CredentialsError(
                f"Credentials secret missing fields: {', '.join(missing)}"
            )
        return content

    def _pebble_layer(
        self, credentials: dict[str, str], tls: bool = False
    ) -> ops.pebble.LayerDict:
        environment = {
            "LANDSCAPE_API_URI": str(self.config["landscape-api-uri"]),
            "LANDSCAPE_API_KEY": credentials["api-key"],
            "LANDSCAPE_API_SECRET": credentials["api-secret"],
        }
        if tls:
            environment["LANDSCAPE_MCP_TLS_CERT"] = TLS_CERT_PATH
            environment["LANDSCAPE_MCP_TLS_KEY"] = TLS_KEY_PATH
        # Pebble's HTTP check does not trust the private CA, so probe the port.
        check = (
            {"tcp": {"port": self.port}}
            if tls
            else {"http": {"url": f"http://localhost:{self.port}{HEALTH_PATH}"}}
        )
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
                    "environment": environment,
                }
            },
            "checks": {
                "up": {
                    "override": "replace",
                    "level": "alive",
                    **check,
                }
            },
        }

    def _reconcile(self, event: ops.EventBase) -> None:
        """Reconcile the workload and relation data with the current config."""
        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.defer()
            return

        try:
            credentials = self._credentials()
        except CredentialsError as e:
            self.unit.status = ops.BlockedStatus(str(e))
            return

        tls = self._tls_related()
        assigned = self._assigned_certificate() if tls else None
        self._send_ca(assigned[0] if assigned else None)
        if tls and assigned is None:
            self.unit.status = ops.WaitingStatus("Waiting for TLS certificate")
            return

        tls_files_changed = False
        if assigned is not None:
            tls_files_changed = self._push_tls_files(container, *assigned)

        container.add_layer(
            CONTAINER_NAME,
            self._pebble_layer(credentials, tls=assigned is not None),
            combine=True,
        )
        container.replan()
        if tls_files_changed:
            # Replan does not restart a service whose layer is unchanged, but the
            # server only reads the certificate at startup.
            container.restart(CONTAINER_NAME)
        self._provide_haproxy_route(https=assigned is not None)
        self.unit.status = ops.ActiveStatus()

    def _send_ca(self, certificate: ProviderCertificate | None) -> None:
        """Publish the issuing CA to HAProxy, or withdraw it when TLS is off."""
        if not self.unit.is_leader():
            return
        if certificate is None:
            self.ca_transfer.remove_all_certificates()
            return
        self.ca_transfer.add_certificates({str(certificate.ca)})

    def _provide_haproxy_route(self, https: bool = False) -> None:
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
            protocol="https" if https else "http",
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
