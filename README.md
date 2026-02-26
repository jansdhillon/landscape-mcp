# landscape-api-mcp

## Running the MCP server

Make sure you have uv installed:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Edit `.env.example` with your real Landscape SaaS API credentials, remove the `.example` extension, and run `source .env`.

Then, clone this repo and run `uv run landscape_api.py`.

After starting the server, AI agents can use the tools to query Landscape while authenticating with the credentials provided in the environment variables. For example, you can ask it about the licenses for a given account.

### VSCode

If you're using VSCode, the server can be started automatically by adding an entry to `mcp.json`:

```json
{
	"servers": {
		"landscape-api-mcp": {
			"type": "stdio",
			"command": "uv",
			"args": [
				"run",
				"--directory",
				"/home/jan.dhillon@canonical.com/landscape-api-mcp",
				"landscape_api.py"
			],
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
