from typing import Any
import json
import httpx
from mcp.server.fastmcp import FastMCP
import os
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

mcp = FastMCP("landscape-api")

LANDSCAPE_API_BASE = os.getenv(
    "LANDSCAPE_API_URI", "https://landscape.canonical.com/api/"
)
LANDSCAPE_API_KEY = os.getenv("LANDSCAPE_API_KEY")
LANDSCAPE_API_SECRET = os.getenv("LANDSCAPE_API_SECRET")
_access_token: str | None = None
_user_email: str | None = None


async def get_access_token() -> str | None:
    global _access_token, _user_email

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
            _access_token = data.get("token")
            _user_email = data.get("email")
            logging.info(f"Successfully authenticated as {_user_email}")
            return _access_token
        except Exception as e:
            logging.error(f"Failed to get access token: {e}")
            return None


async def make_api_request(
    method: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    token = await get_access_token()
    if not token:
        return None

    url = LANDSCAPE_API_BASE.rstrip("/")
    query_params = {"action": method, "version": "2011-08-01"}
    if params:
        query_params.update(params)

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url, params=query_params, headers=headers, timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"API request failed: {e}")
            return None


@mcp.tool()
async def get_accounts(
    email: str | None = None,
    account_name: str | None = None,
) -> str:
    params = {}

    if email:
        params["email"] = email
    elif account_name:
        params["account_name"] = account_name
    else:
        if not _user_email:
            await get_access_token()
        if not _user_email:
            return "Unable to authenticate and get user email"
        params["email"] = _user_email

    data = await make_api_request("GetAccounts", params)

    if not data:
        return "Unable to fetch accounts"

    return json.dumps(data, indent=2)


@mcp.tool()
async def get_licenses(account_name: str | None = None) -> str:
    if account_name:
        data = await make_api_request("GetAccounts", {"account_name": account_name})
        if not data or not data:
            return f"Unable to fetch licenses for account: {account_name}"
        account = data[0] if isinstance(data, list) else data
        licenses = account.get("licenses", [])
        return json.dumps(licenses, indent=2)

    if not _user_email:
        await get_access_token()

    if not _user_email:
        return "Unable to authenticate and get user email"

    accounts_data = await make_api_request("GetAccounts", {"email": _user_email})

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
