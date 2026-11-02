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
"""Time entries logged against tickets."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import GoreloClient
from ._common import READ_ONLY, WRITES, ClientFactory, Cursor, Limit, compact, data, page_cursor, paging, run_tool

# 1 = Billable, 2 = No charge, 3 = Non-billable (CreateTimeEntryCommand.BillableStatusId, fixed enum).
_BILLABLE_STATUS_TO_ID = {"billable": 1, "no_charge": 2, "non_billable": 3}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def gorelo_list_time_entries(
        limit: Limit = 50,
        cursor: Cursor = None,
        client_ids: Annotated[str | None, Field(description="Comma-separated client ids.")] = None,
        ticket_ids: Annotated[str | None, Field(description="Comma-separated ticket ids.")] = None,
        user_ids: Annotated[str | None, Field(description="Comma-separated technician (user) ids.")] = None,
        started_since: Annotated[str | None, Field(description="ISO timestamp: started on or after.")] = None,
        started_before: Annotated[str | None, Field(description="ISO timestamp: started on or before.")] = None,
    ) -> str:
        """List time entries: ticket, user, started/ended timestamps, actual hours, billable status, comment."""

        async def action(client: GoreloClient) -> dict:
            params = paging(limit, cursor) | compact(
                {
                    "ClientIds": client_ids,
                    "TicketIds": ticket_ids,
                    "UserIds": user_ids,
                    "StartedSince": started_since,
                    "StartedBefore": started_before,
                }
            )
            return page_cursor(await client.get("v1/time-entries", params), "time_entries")

        return await run_tool("gorelo_list_time_entries", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def gorelo_log_time_entry(
        ticket_id: Annotated[str, Field(description="Gorelo ticket id (uuid) to log time against.", min_length=1)],
        started_on: Annotated[str, Field(description="ISO timestamp the work started.", min_length=1)],
        ended_on: Annotated[str | None, Field(description="ISO timestamp the work ended. Exactly one of ended_on/actual_hours is required.")] = None,
        actual_hours: Annotated[float | None, Field(description="Hours worked. Exactly one of ended_on/actual_hours is required.", gt=0)] = None,
        comment: Annotated[str | None, Field(description="Note describing the work.")] = None,
        billable_status: Annotated[str | None, Field(description="billable, no_charge, or non_billable. Default: the ticket's own billable status.")] = None,
        user_id: Annotated[int | None, Field(description="Technician the time is logged for; default the caller's own identity in Gorelo.", ge=1)] = None,
    ) -> str:
        """Log a time entry against a ticket (started_on, plus ended_on or actual_hours).

        Only when the user explicitly asks.
        """

        async def action(client: GoreloClient) -> Any:
            if (ended_on is None) == (actual_hours is None):
                raise ValueError("Pass exactly one of ended_on or actual_hours, not neither or both.")
            billable_status_id = None
            if billable_status:
                billable_status_id = _BILLABLE_STATUS_TO_ID.get(billable_status.strip().lower())
                if billable_status_id is None:
                    raise ValueError(f"Unknown billable_status {billable_status!r}. Known values: {', '.join(_BILLABLE_STATUS_TO_ID)}.")
            body = compact(
                {
                    "TicketId": ticket_id,
                    "StartedOn": started_on,
                    "EndedOn": ended_on,
                    "ActualHours": actual_hours,
                    "Comment": comment,
                    "BillableStatusId": billable_status_id,
                    "UserId": user_id,
                }
            )
            return data(await client.post("v1/time-entries", body))

        return await run_tool("gorelo_log_time_entry", client_factory, action)
