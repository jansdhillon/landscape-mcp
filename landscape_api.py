from typing import Any
import json
import httpx
from mcp.server.fastmcp import FastMCP
import os
import logging

mcp = FastMCP("landscape-api")

LANDSCAPE_API_BASE = os.getenv(
    "LANDSCAPE_API_URI", "https://landscape.canonical.com/api/"
)
LANDSCAPE_API_KEY = os.getenv("LANDSCAPE_API_KEY")
LANDSCAPE_API_SECRET = os.getenv("LANDSCAPE_API_SECRET")
_access_token: str | None = None


async def get_access_token() -> str | None:
    """Get access token from Landscape API."""
    global _access_token

    if _access_token:
        return _access_token

    if not LANDSCAPE_API_KEY or not LANDSCAPE_API_SECRET:
        logging.error("LANDSCAPE_API_KEY and LANDSCAPE_API_SECRET must be set")
        return None

    url = f"{LANDSCAPE_API_BASE}login/access-key"
    body = {
        "access_key": LANDSCAPE_API_KEY,
        "secret_key": LANDSCAPE_API_SECRET,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=body, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            _access_token = data.get("access_token")
            return _access_token
        except Exception as e:
            logging.error(f"Failed to get access token: {e}")
            return None


async def make_api_request(
    method: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Make an authenticated request to the Landscape API."""
    token = await get_access_token()
    if not token:
        return None

    url = f"{LANDSCAPE_API_BASE}{method}"
    body = {"action": method, "version": "2011-08-01", "params": params or {}}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=body, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"API request failed: {e}")
            return None


@mcp.tool()
async def get_accounts() -> str:
    """Get all accounts accessible to the authenticated user."""
    data = await make_api_request("GetAccounts", {})

    if not data:
        return "Unable to fetch accounts"

    return json.dumps(data, indent=2)


@mcp.tool()
async def get_account(account_name: str) -> str:
    """Get a specific account by name.

    Args:
        account_name: The name of the account to retrieve
    """
    data = await make_api_request("GetAccounts", {"account_name": account_name})

    if not data:
        return f"Unable to fetch account: {account_name}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def get_licenses(account_name: str | None = None) -> str:
    """Get licenses from Landscape. If account_name is provided, returns licenses for that account only.

    Args:
        account_name: Optional account name to filter licenses by
    """
    if account_name:
        data = await make_api_request("GetAccounts", {"account_name": account_name})
        if not data or not data:
            return f"Unable to fetch licenses for account: {account_name}"
        account = data[0] if isinstance(data, list) else data
        licenses = account.get("licenses", [])
        return json.dumps(licenses, indent=2)

    accounts_data = await make_api_request("GetAccounts", {})

    if not accounts_data:
        return "Unable to fetch licenses"

    all_licenses = []
    for account in accounts_data:
        account_name = account.get("account", "unknown")
        licenses = account.get("licenses", [])
        for license in licenses:
            all_licenses.append({"account": account_name, **license})

    return json.dumps(all_licenses, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
