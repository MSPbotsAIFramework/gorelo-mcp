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
"""Clients (customer organizations) and their contacts.

Note (verified against the live OpenAPI document, 2026-11-02): unlike tickets,
Gorelo publishes no name-lookup endpoint for client/contact status — only
`GET /v1/clients/{id}` returns a {Id, Name} Status object per record, with no
`/v1/clients/statuses` to resolve a name against. So these list tools take
`status_ids` (numeric, as Gorelo's own API does), not `status_names`.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import GoreloClient
from ._common import READ_ONLY, ClientFactory, Cursor, Limit, compact, data, page_cursor, paging, run_tool

ClientId = Annotated[int, Field(description="Gorelo client (customer organization) id.", ge=1)]
ContactId = Annotated[int, Field(description="Gorelo contact id.", ge=1)]
StatusIds = Annotated[str | None, Field(description="Comma-separated status ids (see the Status.Id on a record); Gorelo has no status-name lookup for this list.")]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_clients(
        query: Annotated[str | None, Field(description="Text to search for in client name/billing name/alternate name.")] = None,
        limit: Limit = 50,
        cursor: Cursor = None,
        status_ids: StatusIds = None,
        group_ids: Annotated[str | None, Field(description="Comma-separated client group ids.")] = None,
        updated_since: Annotated[str | None, Field(description="ISO timestamp: updated on or after.")] = None,
        updated_before: Annotated[str | None, Field(description="ISO timestamp: updated on or before.")] = None,
        created_since: Annotated[str | None, Field(description="ISO timestamp: created on or after.")] = None,
        created_before: Annotated[str | None, Field(description="ISO timestamp: created on or before.")] = None,
    ) -> str:
        """List clients (customer organizations): id, name, status, billing name, type."""

        async def action(client: GoreloClient) -> dict:
            params = paging(limit, cursor) | compact(
                {
                    "Query": query,
                    "StatusIds": status_ids,
                    "GroupIds": group_ids,
                    "UpdatedSince": updated_since,
                    "UpdatedBefore": updated_before,
                    "CreatedSince": created_since,
                    "CreatedBefore": created_before,
                }
            )
            return page_cursor(await client.get("v1/clients", params), "clients")

        return await run_tool("gorelo_list_clients", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_get_client(client_id: ClientId) -> str:
        """Get one client's full record: name, status, billing name, domains, groups, type."""

        async def action(client: GoreloClient) -> Any:
            return data(await client.get(f"v1/clients/{client_id}"))

        return await run_tool("gorelo_get_client", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_contacts(
        query: Annotated[str | None, Field(description="Text to search for in contact name/email.")] = None,
        limit: Limit = 50,
        cursor: Cursor = None,
        client_ids: Annotated[str | None, Field(description="Comma-separated client ids.")] = None,
        status_ids: StatusIds = None,
        updated_since: Annotated[str | None, Field(description="ISO timestamp: updated on or after.")] = None,
        updated_before: Annotated[str | None, Field(description="ISO timestamp: updated on or before.")] = None,
        created_since: Annotated[str | None, Field(description="ISO timestamp: created on or after.")] = None,
        created_before: Annotated[str | None, Field(description="ISO timestamp: created on or before.")] = None,
    ) -> str:
        """List contacts at one or more clients: id, name, email, phone, job title, status."""

        async def action(client: GoreloClient) -> dict:
            params = paging(limit, cursor) | compact(
                {
                    "Query": query,
                    "ClientIds": client_ids,
                    "StatusIds": status_ids,
                    "UpdatedSince": updated_since,
                    "UpdatedBefore": updated_before,
                    "CreatedSince": created_since,
                    "CreatedBefore": created_before,
                }
            )
            return page_cursor(await client.get("v1/contacts", params), "contacts")

        return await run_tool("gorelo_list_contacts", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_get_contact(contact_id: ContactId) -> str:
        """Get one contact's full record: name, email, phone, job title, client, location, status."""

        async def action(client: GoreloClient) -> Any:
            return data(await client.get(f"v1/contacts/{contact_id}"))

        return await run_tool("gorelo_get_contact", client_factory, action)
