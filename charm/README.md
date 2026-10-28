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

## Continuous publishing

Pushes to `main` publish automatically (amd64 only):

| Change | Workflow | Result |
| --- | --- | --- |
| `cmd/`, `internal/`, `go.mod`, `go.sum`, `rockcraft.yaml` | `publish-image.yaml` | Rock pushed to `ghcr.io/jansdhillon/landscape-mcp` as `latest` and `sha-<commit>`, uploaded as a new `landscape-mcp-image` resource revision, charm released to `latest/edge` with it |
| `charm/` (excluding tests and docs) | `publish-charm.yaml` | Charm released to `latest/edge` with the latest `landscape-mcp-image` revision |

Both workflows run their lint and tests first and can also be started by hand
from the Actions tab. Releases to Charmhub are serialised, so a push that
touches both the server and the charm ends with the new charm and new image.

The repository needs a `CHARMHUB_TOKEN` secret. Export one scoped to this charm
(the default lifetime is 30 hours, so set `--ttl`):

```sh
charmcraft login --export charmhub-token --charm landscape-mcp \
  --channel latest/edge \
  --permission package-manage-releases --permission package-manage-revisions \
  --permission package-view-revisions --ttl 31536000
gh secret set CHARMHUB_TOKEN < charmhub-token && rm charmhub-token
```

The image is pushed with the workflow's `GITHUB_TOKEN`. If the GHCR package was
first created by a manual push, grant this repository write access under the
package's settings (Manage Actions access).

To publish by hand instead:

```sh
charmcraft upload-resource landscape-mcp landscape-mcp-image \
  --image=docker://ghcr.io/jansdhillon/landscape-mcp:latest
charmcraft upload landscape-mcp_ubuntu@24.04-amd64.charm \
  --release latest/edge --resource landscape-mcp-image:<resource-revision>
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

Until `landscape-api-uri` is set and the secret is configured and granted, the
unit is blocked. `landscape-api-uri` has no default. Rotating the secret
(`juju update-secret`) restarts the workload with the new credentials.

## Publish behind HAProxy

Relate to the HAProxy charm that fronts `landscape-server` (a cross-model
relation if it lives in another model):

```sh
juju relate landscape-mcp:mcp-haproxy-route haproxy
```

The route hostname is the host of `landscape-api-uri`, so set that to the
external Landscape URL (the `root_url` of `landscape-server`). HAProxy ignores
routes without a hostname; if the URI has none, the unit is blocked.

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

If HAProxy lives in another model, offer every endpoint you need in one
offer, comma-separated. Running `juju offer` again with a different endpoint
replaces the offer's endpoint list instead of adding to it, and fails if that
would drop an endpoint that is in use:

```sh
# In the HAProxy model
juju offer haproxy:haproxy-route,receive-ca-certs
juju offer self-signed-certificates:certificates certs

# In the landscape-mcp model
juju consume <controller>:<owner>/<model>.haproxy
juju consume <controller>:<owner>/<model>.certs
juju relate landscape-mcp:mcp-haproxy-route haproxy:haproxy-route
juju relate landscape-mcp:send-ca-cert haproxy:receive-ca-certs
juju relate landscape-mcp:certificates certs
```

If the consumed SAAS still lacks an endpoint after you change an offer,
`juju remove-saas` it and `juju consume` it again. Alternatively, publish the
extra endpoint as a separately named offer
(e.g. `juju offer haproxy:receive-ca-certs haproxy-ca`) and consume that.

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
