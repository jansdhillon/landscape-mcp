# landscape-mcp

An [MCP](https://modelcontextprotocol.io/) server for [Landscape](https://landscape.canonical.com/), written in Go with the [official Go MCP SDK](https://github.com/modelcontextprotocol/go-sdk). It lets AI agents query Landscape accounts, licenses, and registered computers.

## Tools and prompts

| Name | Kind | Description |
|---|---|---|
| `get_accounts` | tool | Get Landscape accounts, optionally filtered by `email` or `account_name` |
| `get_licenses` | tool | Get licenses for an account, or aggregated across all accessible accounts |
| `get_computers` | tool | Get all registered computers (hardware, Ubuntu Pro status, distribution, tags, last exchange) |
| `audit_account` | prompt | Audit an account: license expiry, Ubuntu Pro status, stale computers |

## Configuration

The server reads its configuration from the environment:

| Variable | Required | Default | Description |
|---|---|---|---|
| `LANDSCAPE_API_KEY` | yes | - | Landscape API access key |
| `LANDSCAPE_API_SECRET` | yes | - | Landscape API secret key |
| `LANDSCAPE_API_URI` | no | `https://landscape.canonical.com/api/` | Landscape API base URL |

The server starts without credentials so clients can list its tools; tool calls fail with an error naming the missing variables until they are set.

## Building

Requires Go 1.26+:

```sh
go build -o landscape-mcp ./cmd/landscape-mcp
```

## Running

Two transports are available, selected with `-transport` (env `LANDSCAPE_MCP_TRANSPORT`):

- `stdio` (default): for local agent clients launching the binary directly.
- `http`: streamable HTTP at `/mcp` on `-addr` (env `LANDSCAPE_MCP_HTTP_ADDR`, default `:8080`), with a `/healthz` endpoint for load balancer health checks. Used by the [charm](charm/) and [rock](rockcraft.yaml).

```sh
./landscape-mcp -transport http -addr :8080
```

### VSCode

Add an entry to `mcp.json`:

```json
{
	"servers": {
		"landscape-mcp": {
			"type": "stdio",
			"command": "/path/to/landscape-mcp",
			"env": {
				"LANDSCAPE_API_URI": "${input:landscape-api-uri}",
				"LANDSCAPE_API_KEY": "${input:landscape-api-access-key}",
				"LANDSCAPE_API_SECRET": "${input:landscape-api-secret-key}"
			}
		}
	},
	"inputs": [
		{
			"id": "landscape-api-uri",
			"type": "promptString",
			"description": "API URI for Landscape"
		},
		{
			"id": "landscape-api-access-key",
			"type": "promptString",
			"description": "API Access Key for Landscape"
		},
		{
			"id": "landscape-api-secret-key",
			"type": "promptString",
			"description": "API Secret Key for Landscape",
			"password": true
		}
	]
}
```

## Charmed deployment

The [`charm/`](charm/) directory contains a Kubernetes charm that deploys the
server (HTTP transport) and can publish it behind the same HAProxy as the
`landscape-server` charm via an `haproxy-route` relation - clients can then
connect directly to a local binary or to the charmed deployment. See
[charm/README.md](charm/README.md).

## Development

```sh
go build ./...
go vet ./...
go test ./...
```

### API client

v2 API calls (e.g. `get_computers`) go through the generated [landscape-go-api-client](https://github.com/jansdhillon/landscape-go-api-client), which is regenerated from the [landscape-openapi-spec](https://github.com/jansdhillon/landscape-openapi-spec). Legacy API actions (`GetAccounts`) use the shim in `internal/landscape/` - the legacy API is not OpenAPI-specifiable and stays out of the spec permanently.

The spec grows demand-driven: endpoints are added only when a consumer (this MCP, the Terraform provider) needs them. When Canonical publishes an official spec, point the client repo at it, regenerate, and the MCP follows.
