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
"""Managed-device (RMM) asset inventory. Patch/hardware/app detail and uptime-monitor
management are out of scope for v1 (see Non-goals in docs/tickets/PRD-21211.md)."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import GoreloClient
from ._common import READ_ONLY, ClientFactory, Cursor, Limit, compact, data, page_cursor, paging, run_tool

AgentAssetId = Annotated[str, Field(description="Gorelo managed-device (agent asset) id (uuid).", min_length=1)]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_agent_assets(
        query: Annotated[str | None, Field(description="Text to search for in device name/display name.")] = None,
        limit: Limit = 50,
        cursor: Cursor = None,
        client_ids: Annotated[str | None, Field(description="Comma-separated client ids.")] = None,
        status_ids: Annotated[str | None, Field(description="Comma-separated status ids; Gorelo has no status-name lookup for assets.")] = None,
    ) -> str:
        """List managed devices (RMM asset inventory): id, name, display name, status, client."""

        async def action(client: GoreloClient) -> dict:
            params = paging(limit, cursor) | compact({"Query": query, "ClientIds": client_ids, "StatusIds": status_ids})
            return page_cursor(await client.get("v1/assets/agents", params), "agent_assets")

        return await run_tool("gorelo_list_agent_assets", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_get_agent_asset(agent_asset_id: AgentAssetId) -> str:
        """Get one managed device's full record: name, status, client, OS, hardware, network."""

        async def action(client: GoreloClient) -> Any:
            return data(await client.get(f"v1/assets/agents/{agent_asset_id}"))

        return await run_tool("gorelo_get_agent_asset", client_factory, action)
