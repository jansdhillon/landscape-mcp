from typing import Any
import json
import httpx
from mcp.server.fastmcp import FastMCP
import os
import logging
import sys
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

LANDSCAPE_API_KEY = os.getenv("LANDSCAPE_API_KEY")
LANDSCAPE_API_SECRET = os.getenv("LANDSCAPE_API_SECRET")
LANDSCAPE_API_BASE_URL = os.getenv(
    "LANDSCAPE_API_URI", "https://landscape.canonical.com/api/"
)

mcp = FastMCP("landscape-api")

type Params = dict[str, Any]
type ApiResponse = dict[str, Any]


class LoginResponse(BaseModel):
    jwt: str
    email: str


class LoginError(Exception):
    """Failed to login"""


async def login() -> LoginResponse:
    if not LANDSCAPE_API_KEY or not LANDSCAPE_API_SECRET or not LANDSCAPE_API_BASE_URL:
        e_msg = (
            "LANDSCAPE_API_KEY, LANDSCAPE_API_SECRET, and LANDSCAPE_API_URI must be set"
        )
        logging.error(e_msg)
        raise LoginError(e_msg)

    url = f"{LANDSCAPE_API_BASE_URL}login/access-key"
    body = {
        "access_key": LANDSCAPE_API_KEY,
        "secret_key": LANDSCAPE_API_SECRET,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=body, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            jwt = data.get("token")
            email = data.get("email")
            logging.info(f"Logged in as {email}")
            return LoginResponse(jwt=jwt, email=email)

        except Exception as e:
            e_msg = f"Failed to get access token: {e}"
            logging.error(e_msg)
            raise LoginError(e_msg)


async def legacy_api_request(
    method: str, params: Params | None = None
) -> ApiResponse | None:
    try:
        res = await login()
    except LoginError as e:
        logging.error("Failed to login: %s", str(e))
        raise e

    url = LANDSCAPE_API_BASE_URL.rstrip("/")
    query_params = {"action": method, "version": "2011-08-01"}
    if params:
        query_params.update(params)

    headers = {"Authorization": f"Bearer {res.jwt}"}

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


async def rest_api_request(
    method: str, endpoint: str, params: Params | None = None
) -> ApiResponse | None:
    try:
        res = await login()
    except LoginError as e:
        logging.error("Failed to login: %s", str(e))
        raise e

    url = f"{LANDSCAPE_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {res.jwt}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method, url, params=params, headers=headers, timeout=30.0
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
    """Get Landscape accounts. Optionally filter by email address or account name."""
    params = {}

    if email:
        params["email"] = email
    elif account_name:
        params["account_name"] = account_name

    data = await legacy_api_request("GetAccounts", params)

    if not data:
        return "Unable to fetch accounts"

    return json.dumps(data, indent=2)


@mcp.tool()
async def get_licenses(account_name: str | None = None) -> str:
    """Get Landscape licenses by account name. Returns all licenses across all (accessible) accounts if no account name is provided."""
    if account_name:
        data = await legacy_api_request("GetAccounts", {"account_name": account_name})
        if not data:
            return f"Unable to fetch licenses for account: {account_name}"
        account = data[0] if isinstance(data, list) else data
        licenses = account.get("licenses", [])
        return json.dumps(licenses, indent=2)

    res = await login()
    accounts_data = await legacy_api_request("GetAccounts", {"email": res.email})

    if not accounts_data:
        return "Unable to fetch licenses"

    all_licenses: list[dict[str, Any]] = []
    for account in accounts_data:
        account_name = account.get("account", "unknown")
        licenses = account.get("licenses", [])
        for license in licenses:
            all_licenses.append({"account": account_name, **license})

    return json.dumps(all_licenses, indent=2)


@mcp.tool()
async def get_computers() -> str:
    """Get all computers registered in Landscape, including their hardware info, Ubuntu Pro status, distribution, tags, and last exchange time."""
    data = await rest_api_request("GET", "/computers")

    if not data:
        return "Unable to fetch computers"

    return json.dumps(data, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
