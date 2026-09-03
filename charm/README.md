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
  --config landscape-api-uri=https://landscape.example.com/api/ \
  --config landscape-api-key=<access-key> \
  --config landscape-api-secret=<secret-key>
```

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

## Development

```sh
make test   # unit tests (ops.testing scenario)
make check  # ruff lint + format check
make lint   # ruff with fixes
```
