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
"""Service desk tickets, comments and the status/type/priority reference lookups."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._lookups import by_name, ids_by_names, name_or_id_to_int, priority_rows, source_rows, status_rows, type_rows
from ..api_client import GoreloClient
from ._common import READ_ONLY, WRITES, ClientFactory, Cursor, Limit, compact, data, page_cursor, paging, run_tool

TicketId = Annotated[str, Field(description="Gorelo ticket id (uuid).", min_length=1)]

# TicketPriority is a fixed 0-4 enum on the write side (CreateTicketCommand.PriorityId); the five
# names below are the ones GET /v1/tickets/priorities itself returns for that scale.
_PRIORITY_NAME_TO_ID = {"none": 0, "urgent": 1, "high": 2, "normal": 3, "low": 4}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_tickets(
        query: Annotated[str | None, Field(description="Text to search for in tickets (title, number, description ...).")] = None,
        limit: Limit = 50,
        cursor: Cursor = None,
        status_names: Annotated[str | None, Field(description="Comma-separated status names, e.g. New,In Progress.")] = None,
        priority_names: Annotated[str | None, Field(description="Comma-separated priority names: none, urgent, high, normal, low.")] = None,
        type_names: Annotated[str | None, Field(description="Comma-separated ticket type names.")] = None,
        client_ids: Annotated[str | None, Field(description="Comma-separated client ids.")] = None,
        contact_ids: Annotated[str | None, Field(description="Comma-separated contact ids.")] = None,
        lead_assignee_ids: Annotated[str | None, Field(description="Comma-separated lead-assignee (technician) ids.")] = None,
        updated_since: Annotated[str | None, Field(description="ISO timestamp: updated on or after.")] = None,
        updated_before: Annotated[str | None, Field(description="ISO timestamp: updated on or before.")] = None,
        created_since: Annotated[str | None, Field(description="ISO timestamp: created on or after.")] = None,
        created_before: Annotated[str | None, Field(description="ISO timestamp: created on or before.")] = None,
    ) -> str:
        """List service desk tickets: id, number, title, status, priority, type, client, contact, assignees."""

        async def action(client: GoreloClient) -> dict:
            status_ids = ",".join(str(i) for i in ids_by_names(await status_rows(client), status_names, "status")) if status_names else None
            priority_ids = (
                ",".join(str(i) for i in ids_by_names(await priority_rows(client), priority_names, "priority")) if priority_names else None
            )
            type_ids = ",".join(str(i) for i in ids_by_names(await type_rows(client), type_names, "ticket type")) if type_names else None
            params = paging(limit, cursor) | compact(
                {
                    "Query": query,
                    "StatusIds": status_ids,
                    "PriorityIds": priority_ids,
                    "TypeIds": type_ids,
                    "ClientIds": client_ids,
                    "ContactIds": contact_ids,
                    "LeadAssigneeIds": lead_assignee_ids,
                    "UpdatedSince": updated_since,
                    "UpdatedBefore": updated_before,
                    "CreatedSince": created_since,
                    "CreatedBefore": created_before,
                }
            )
            return page_cursor(await client.get("v1/tickets", params), "tickets")

        return await run_tool("gorelo_list_tickets", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_get_ticket(ticket_id: TicketId) -> str:
        """Get one ticket's full record (description, source, location, assignees, tags, linked assets)."""

        async def action(client: GoreloClient) -> Any:
            return data(await client.get(f"v1/tickets/{ticket_id}"))

        return await run_tool("gorelo_get_ticket", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_ticket_comments(
        ticket_id: TicketId,
        limit: Limit = 50,
        cursor: Cursor = None,
        conversation_type: Annotated[str | None, Field(description="Filter: Public, Private, SideConversation, or Approval.")] = None,
        conversation_id: Annotated[str | None, Field(description="Filter: only comments in this conversation.")] = None,
    ) -> str:
        """List a ticket's comments across its conversations (Public, Private, side conversations, approvals)."""

        async def action(client: GoreloClient) -> dict:
            params = paging(limit, cursor) | compact({"ConversationType": conversation_type, "ConversationId": conversation_id})
            return page_cursor(await client.get(f"v1/tickets/{ticket_id}/comments", params), "comments")

        return await run_tool("gorelo_list_ticket_comments", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_ticket_statuses() -> str:
        """List the tenant's ticket statuses (id, name) used by status_names and gorelo_create_ticket."""

        async def action(client: GoreloClient) -> dict:
            return {"statuses": await status_rows(client)}

        return await run_tool("gorelo_list_ticket_statuses", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_ticket_types() -> str:
        """List the tenant's ticket types (id, name) used by type_names and gorelo_create_ticket."""

        async def action(client: GoreloClient) -> dict:
            return {"types": await type_rows(client)}

        return await run_tool("gorelo_list_ticket_types", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def gorelo_create_ticket(
        title: Annotated[str, Field(description="Ticket title/subject. Maximum 250 characters.", min_length=1, max_length=250)],
        client_id: Annotated[int, Field(description="Client (customer organization) the ticket belongs to.", ge=1)],
        status_name_or_id: Annotated[str, Field(description="Status name (see gorelo_list_ticket_statuses) or its numeric id.", min_length=1)],
        type_name_or_id: Annotated[str, Field(description="Ticket type name (see gorelo_list_ticket_types) or its numeric id.", min_length=1)],
        group_id: Annotated[int, Field(description="Technician group the ticket is assigned to.", ge=1)],
        description: Annotated[str | None, Field(description="Ticket details.")] = None,
        contact_id: Annotated[int | None, Field(description="Contact at the client.", ge=1)] = None,
        priority_name: Annotated[str | None, Field(description="Priority name: none, urgent, high, normal, low. Default: none.")] = None,
        source_name: Annotated[str | None, Field(description="Source name (see Gorelo's ticket sources). Omit to leave unset.")] = None,
    ) -> str:
        """Create a service desk ticket for a client. Only when the user explicitly asks."""

        async def action(client: GoreloClient) -> Any:
            status_id = name_or_id_to_int(status_name_or_id, await status_rows(client), "status")
            type_id = name_or_id_to_int(type_name_or_id, await type_rows(client), "ticket type")
            priority_id = None
            if priority_name:
                priority_id = _PRIORITY_NAME_TO_ID.get(priority_name.strip().lower())
                if priority_id is None:
                    raise ValueError(f"Unknown priority {priority_name!r}. Known values: {', '.join(_PRIORITY_NAME_TO_ID)}.")
            source_id = by_name(await source_rows(client), source_name, "source") if source_name else None
            body = compact(
                {
                    "Title": title,
                    "ClientId": client_id,
                    "StatusId": status_id,
                    "TypeId": type_id,
                    "GroupId": group_id,
                    "Description": description,
                    "ContactId": contact_id,
                    "PriorityId": priority_id,
                    "SourceId": source_id,
                }
            )
            created = data(await client.post("v1/tickets", body))
            ticket_id = created.get("Id") if isinstance(created, dict) else None
            if not ticket_id:
                return created
            # CreateTicketResult only carries Id; fetch the record once more for DisplayNumber.
            ticket = data(await client.get(f"v1/tickets/{ticket_id}"))
            display_number = ticket.get("DisplayNumber") if isinstance(ticket, dict) else None
            return compact({"id": ticket_id, "display_number": display_number})

        return await run_tool("gorelo_create_ticket", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def gorelo_add_ticket_comment(
        ticket_id: TicketId,
        body: Annotated[str, Field(description="Comment body as HTML (plain text is accepted).", min_length=1)],
        conversation_id: Annotated[
            str | None,
            Field(description="Post into this prior side-conversation instead of the main Public thread. Approval conversations are not supported by this tool."),
        ] = None,
    ) -> str:
        """Add a comment to a ticket's Public thread or a prior side-conversation.

        Only when the user explicitly asks.
        """

        async def action(client: GoreloClient) -> Any:
            # 1 = Public (the ticket's main thread), 3 = Side Conversation; Private (2) and
            # Approval (4) are out of scope for this tool (see docstring).
            conversation_type_id = 3 if conversation_id else 1
            payload = compact({"ConversationTypeId": conversation_type_id, "ConversationId": conversation_id, "Body": body})
            created = data(await client.post(f"v1/tickets/{ticket_id}/comments", payload))
            return created

        return await run_tool("gorelo_add_ticket_comment", client_factory, action)
