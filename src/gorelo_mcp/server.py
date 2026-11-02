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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import GoreloClient, GoreloCredentials
from .config import REGION_HOSTS

HEADER_API_KEY = "X-Gorelo-Api-Key"
HEADER_REGION = "X-Gorelo-Region"
REQUIRED_HEADERS = [HEADER_API_KEY, HEADER_REGION]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[GoreloCredentials | None] = contextvars.ContextVar("gorelo_credentials", default=None)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("gorelo_request_id", default="-")

INSTRUCTIONS = (
    "Gorelo is a combined PSA/RMM: service desk tickets for the MSP's clients, with clients, "
    "contacts, billing contracts, time tracking and the managed-device (RMM) asset inventory.\n"
    "Usage:\n"
    "- Find tickets: gorelo_list_tickets (query text, status/priority/type names, client, "
    "updated/created date range) -> gorelo_get_ticket.\n"
    "- Status/type/priority names: gorelo_list_ticket_statuses / _types resolve the ids "
    "gorelo_list_tickets and gorelo_create_ticket need; priority names are none/urgent/high/"
    "normal/low, no lookup call needed for those.\n"
    "- Who: gorelo_list_clients / _list_contacts give the client_id and contact_id other tools "
    "take; gorelo_list_contracts for billing contracts.\n"
    "- Time: gorelo_list_time_entries(ticket_ids, client_ids, user_ids, started_since/before).\n"
    "- Devices: gorelo_list_agent_assets / gorelo_get_agent_asset for the RMM-managed inventory.\n"
    "- Lists page with limit (default 50, max 200) and an opaque cursor from the previous page's "
    "next_cursor.\n"
    "Creating tickets, adding comments and logging time write to the live PSA: only when the "
    "user explicitly asks."
)


def get_client_from_context() -> GoreloClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return GoreloClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def _clean_region(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    text = text.lower()
    return text if text in REGION_HOSTS else None


class GatewayCredentialsMiddleware:
    """Reads the Gorelo API key and region on /mcp requests into the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        api_key = _clean(request.headers.get(HEADER_API_KEY))
        region_raw = _clean(request.headers.get(HEADER_REGION))
        region = _clean_region(region_raw)
        missing = [] if api_key else [HEADER_API_KEY]
        if region_raw is None:
            missing.append(HEADER_REGION)
        elif region is None:
            await JSONResponse(
                {
                    "error": "Invalid credentials",
                    "message": f"{HEADER_REGION} must be one of: {', '.join(sorted(REGION_HOSTS))} (got {region_raw!r}).",
                    "required_headers": REQUIRED_HEADERS,
                },
                status_code=401,
            )(scope, receive, send)
            return
        if missing:
            await JSONResponse(
                {"error": "Missing credentials", "message": f"Missing header(s): {', '.join(missing)}", "required_headers": REQUIRED_HEADERS},
                status_code=401,
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(GoreloCredentials(region, api_key))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings=None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="gorelo-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], GoreloClient | None] = get_client_from_context

    from .tools import assets, crm, finance, tickets, time_entries

    for module in (tickets, crm, finance, time_entries, assets):
        module.register(mcp, client_factory)

    return mcp
