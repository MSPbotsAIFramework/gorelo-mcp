# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Credential middleware: 401 on missing/invalid headers, request isolation (TC-GORELO-016/021)."""

import asyncio

import pytest
from starlette.testclient import TestClient

from gorelo_mcp.__main__ import build_http_app
from gorelo_mcp.server import GatewayCredentialsMiddleware, _credentials_var, create_mcp_server, get_client_from_context

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
CREDS = {"X-Gorelo-Api-Key": "key-123", "X-Gorelo-Region": "us"}


def _client() -> TestClient:
    return TestClient(build_http_app(create_mcp_server()))


def test_health_is_local():
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Gorelo-Api-Key": "key-123"},
        {"X-Gorelo-Region": "us"},
        {"X-Gorelo-Api-Key": "${KEY}", "X-Gorelo-Region": "us"},
    ],
)
def test_missing_headers_return_401(headers):
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | headers)
    assert resp.status_code == 401
    assert "Missing header" in resp.json()["message"]


def test_invalid_region_returns_401_naming_accepted_values():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | {"X-Gorelo-Api-Key": "key-123", "X-Gorelo-Region": "eu"})
    assert resp.status_code == 401
    assert "us" in resp.json()["message"] and "au" in resp.json()["message"]


def test_region_is_case_insensitive():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | {"X-Gorelo-Api-Key": "key-123", "X-Gorelo-Region": "AU"})
    assert resp.status_code == 200


def test_tools_list_over_http():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS)
    assert resp.status_code == 200
    for name in ("gorelo_list_tickets", "gorelo_create_ticket", "gorelo_get_agent_asset"):
        assert name in resp.text


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message):
    return None


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, _receive, _send))
    return seen


def test_region_selects_host_and_context_is_reset():
    seen = _run_middleware([(b"x-gorelo-api-key", b" key-abc "), (b"x-gorelo-region", b"au")])
    assert seen["credentials"].api_key == "key-abc" and seen["credentials"].region == "au"
    assert seen["client"].base_url == "https://api.aue.gorelo.io"
    assert seen["client"]._headers()["X-API-Key"] == "key-abc"
    assert _credentials_var.get() is None


def test_concurrent_requests_do_not_share_credentials():
    """TC-GORELO-021: two interleaved requests never see each other's key or host."""
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().api_key
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().api_key))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayCredentialsMiddleware(app)

    def scope(key: bytes, region: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": [(b"x-gorelo-api-key", key), (b"x-gorelo-region", region)]}

    async def both():
        await asyncio.gather(
            middleware(scope(b"tenant-a", b"us"), _receive, _send),
            middleware(scope(b"tenant-b", b"au"), _receive, _send),
        )

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_key():
    seen = _run_middleware([(b"x-gorelo-api-key", b"very-secret-key"), (b"x-gorelo-region", b"us")])
    assert "very-secret-key" not in repr(seen["credentials"])
