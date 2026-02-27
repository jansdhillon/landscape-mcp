# landscape-mcp

## Running the MCP server

Make sure you have uv installed:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Edit `.env.example` with your real Landscape API credentials, remove the `.example` extension, and run `source .env`.

Then, clone this repo and run `uvx landscape-mcp`.

After starting the server, AI agents can use the tools to query Landscape while authenticating with the credentials provided in the environment variables. For example, you can ask it about the computers for a given account.

### VSCode

If you're using VSCode, the server can be started automatically by adding an entry to `mcp.json`:

```json
{
	"servers": {
		"landscape-mcp": {
			"type": "stdio",
			"command": "docker",
			"args": [
				"run", "--rm", "-i",
				"-e", "LANDSCAPE_API_URI=${input:landscape-api-uri}",
				"-e", "LANDSCAPE_API_KEY=${input:landscape-api-access-key}",
				"-e", "LANDSCAPE_API_SECRET=${input:landscape-api-secret-key}",
				"ghcr.io/jansdhillon/landscape-mcp:latest"
			]
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
