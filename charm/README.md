# landscape-mcp-operator

Kubernetes charm for the [Landscape MCP server](..). Runs the server with the
streamable HTTP transport and can publish it through the same HAProxy as the
`landscape-server` charm via the `haproxy-route` relation.

## Build

Build the OCI image (from the repo root) and the charm (from this directory):

```sh
rockcraft pack
cd charm && charmcraft pack
```

## Deploy

```sh
juju add-model landscape-mcp
juju deploy ./landscape-mcp_ubuntu@24.04-amd64.charm landscape-mcp \
  --resource landscape-mcp-image=ghcr.io/jansdhillon/landscape-mcp:latest \
  --config landscape-api-uri=https://landscape.example.com/api/
```

The API credentials come from a Juju secret with the fields `api-key` and
`api-secret`. Create it, grant it to the application, and point the charm at
the secret ID:

```sh
juju add-secret landscape-api-creds api-key=<access-key> api-secret=<secret-key>
juju grant-secret landscape-api-creds landscape-mcp
juju config landscape-mcp landscape-api-credentials=secret:<id>
```

Until the secret is configured and granted, the unit is blocked. Rotating the
secret (`juju update-secret`) restarts the workload with the new credentials.

## Publish behind HAProxy

Relate to the HAProxy charm that fronts `landscape-server` (cross-model
relation if it lives in another model):

```sh
juju relate landscape-mcp:mcp-haproxy-route haproxy
```

HAProxy then routes `<landscape-host>/mcp` to this service. Clients connect
with the streamable HTTP transport, e.g. in VSCode `mcp.json`:

```json
{
	"servers": {
		"landscape-mcp": {
			"type": "http",
			"url": "https://landscape.example.com/mcp"
		}
	}
}
```

Note the backend address advertised is the unit's bind address on the
relation network; HAProxy must be able to route to the k8s workload
(routable pod CIDR, NodePort, or load balancer, depending on the substrate).

## Encrypt traffic to HAProxy

By default HAProxy talks to the pod over plain HTTP. To use HTTPS, relate the
charm to a certificates provider, and send the issuing CA to HAProxy so it can
verify the backend (the HAProxy endpoint is `receive-ca-certs`):

```sh
juju relate landscape-mcp:certificates self-signed-certificates
juju relate landscape-mcp:send-ca-cert haproxy:receive-ca-certs
```

The charm requests a certificate for the unit, the server starts serving
HTTPS with it (`-tls-cert`/`-tls-key`), the Pebble check becomes a TCP check,
and the haproxy route switches to the `https` protocol. The certificate
includes the unit's bind address and in-cluster DNS names as subject
alternative names. Removing the `certificates` relation returns the charm to
plain HTTP. The unit shows `Waiting for TLS certificate` until the provider
issues the certificate.

## Development

```sh
make test   # unit tests (ops.testing scenario)
make check  # ruff lint + format check
make lint   # ruff with fixes
```
