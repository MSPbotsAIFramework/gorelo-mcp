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
"""Request shapes, envelopes and tool behaviour against a mocked Gorelo API (TC-GORELO-001..020)."""

import json

import httpx
import pytest

from gorelo_mcp import api_client
from gorelo_mcp.api_client import GoreloApiError, GoreloClient, GoreloCredentials
from gorelo_mcp.server import _credentials_var, create_mcp_server

CREDS = GoreloCredentials("us", "key-123")

STATUSES = [{"Id": 1, "Name": "New"}, {"Id": 2, "Name": "In Progress"}]
TYPES = [{"Id": 10, "Name": "Incident"}, {"Id": 11, "Name": "Request"}]
PRIORITIES = [
    {"Id": 0, "Name": "None"}, {"Id": 1, "Name": "Urgent"}, {"Id": 2, "Name": "High"},
    {"Id": 3, "Name": "Normal"}, {"Id": 4, "Name": "Low"},
]
SOURCES = [{"Id": 1, "Name": "Email"}, {"Id": 2, "Name": "Phone"}]


def ok_list(items, has_more=False, next_cursor=None, total=None):
    return {
        "IsSuccess": True,
        "StatusCode": 200,
        "Data": items,
        "DataContext": {"Pagination": {"NextCursor": next_cursor, "PreviousCursor": None, "HasMore": has_more, "HasPrevious": False, "TotalCount": total if total is not None else len(items)}},
        "Notifications": [],
    }


def ok_item(item):
    return {"IsSuccess": True, "StatusCode": 200, "Data": item, "DataContext": None, "Notifications": []}


def not_found(message="Ticket not found", code="070404"):
    return httpx.Response(404, json={"IsSuccess": False, "StatusCode": 404, "Data": None, "DataContext": None, "Notifications": [{"Code": code, "Message": message}]})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by method + path (without the leading slash)."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else ok_list([])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.lstrip("/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if isinstance(reply, httpx.Response):
            return reply
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"/{path}" and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


def _lookup_routes():
    return {
        "v1/tickets/statuses": ok_list(STATUSES),
        "v1/tickets/types": ok_list(TYPES),
        "v1/tickets/priorities": ok_list(PRIORITIES),
        "v1/tickets/sources": ok_list(SOURCES),
    }


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> GoreloClient:
    return GoreloClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- client / region host / error shapes ------------------------------------


async def test_api_key_header_and_region_host():
    rec = Recorder()
    await _client(rec).get("v1/tickets", {"PageSize": 1})
    request = rec.requests[0]
    assert request.headers["x-api-key"] == "key-123"
    assert str(request.url) == "https://api.usw.gorelo.io/v1/tickets?PageSize=1"


async def test_au_region_host():
    rec = Recorder()
    client = GoreloClient(GoreloCredentials("au", "k"), httpx.AsyncClient(transport=httpx.MockTransport(rec)))
    await client.get("v1/tickets")
    assert str(rec.requests[0].url).startswith("https://api.aue.gorelo.io/")


async def test_non_2xx_is_mapped_by_status(monkeypatch):
    rec = Recorder({"v1/tickets/5": not_found("Ticket not found", "070404")})
    result = await _call(monkeypatch, rec, "gorelo_get_ticket", {"ticket_id": "5"})
    assert result["error"]["code"] == "not_found"
    assert "Ticket not found" in result["error"]["message"] and "070404" in result["error"]["message"]


async def test_is_success_false_on_200_is_an_error(monkeypatch):
    """TC-GORELO-018: IsSuccess:false with Notifications on an otherwise-2xx status is an error."""
    rec = Recorder(
        {
            "v1/clients/9": {
                "IsSuccess": False, "StatusCode": 200, "Data": None, "DataContext": None,
                "Notifications": [{"Code": "060001", "Message": "Client not found"}],
            }
        }
    )
    result = await _call(monkeypatch, rec, "gorelo_get_client", {"client_id": 9})
    assert result["error"]["code"] == "invalid_argument" and "Client not found" in result["error"]["message"]


async def test_get_retries_5xx_but_posts_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json=ok_list([]))])
    rec = Recorder({"GET v1/tickets": lambda r: next(replies), "POST v1/tickets": lambda r: httpx.Response(500)})
    client = _client(rec)
    await client.get("v1/tickets")
    with pytest.raises(GoreloApiError):
        await client.post("v1/tickets", {})
    assert len(rec.calls("v1/tickets", "GET")) == 2 and len(rec.calls("v1/tickets", "POST")) == 1


# ---- tickets -----------------------------------------------------------------


async def test_list_tickets_no_filters_returns_envelope(monkeypatch):
    """AC1/TC-GORELO-001."""
    rows = [{"Id": "t-1", "DisplayNumber": "T-1", "Title": "Printer down"}]
    rec = Recorder({"v1/tickets": ok_list(rows, has_more=True, next_cursor="abc", total=42)})
    result = await _call(monkeypatch, rec, "gorelo_list_tickets", {})
    assert result == {"tickets": rows, "has_more": True, "next_cursor": "abc", "total_count": 42}
    params = rec.requests[0].url.params
    assert params["PageSize"] == "50" and "Cursor" not in params


async def test_list_tickets_unknown_status_name_errors_without_calling_tickets_endpoint(monkeypatch):
    """AC2/TC-GORELO-002."""
    rec = Recorder(_lookup_routes())
    result = await _call(monkeypatch, rec, "gorelo_list_tickets", {"status_names": "NoSuchStatus"})
    assert result["error"]["code"] == "invalid_argument"
    assert "New" in result["error"]["message"] and "In Progress" in result["error"]["message"]
    assert not rec.calls("v1/tickets", "GET")


async def test_list_tickets_unknown_priority_name_names_the_five_values(monkeypatch):
    """AC2/TC-GORELO-003."""
    rec = Recorder(_lookup_routes())
    result = await _call(monkeypatch, rec, "gorelo_list_tickets", {"priority_names": "urgent,bogus"})
    assert result["error"]["code"] == "invalid_argument"
    for name in ("None", "Urgent", "High", "Normal", "Low"):
        assert name in result["error"]["message"]
    assert not rec.calls("v1/tickets", "GET")


async def test_list_tickets_resolves_names_to_ids(monkeypatch):
    rec = Recorder(_lookup_routes() | {"v1/tickets": ok_list([])})
    await _call(monkeypatch, rec, "gorelo_list_tickets", {"status_names": "New,In Progress", "priority_names": "Urgent", "type_names": "Incident"})
    params = rec.calls("v1/tickets", "GET")[0].url.params
    assert params["StatusIds"] == "1,2" and params["PriorityIds"] == "1" and params["TypeIds"] == "10"


async def test_list_tickets_cursor_round_trip(monkeypatch):
    """TC-GORELO-020: has_more + next_cursor on page 1 fetches page 2, not a repeat."""
    page1 = ok_list([{"Id": "t-1"}], has_more=True, next_cursor="page-2-token")
    page2 = ok_list([{"Id": "t-2"}], has_more=False, next_cursor=None)
    pages = iter([page1, page2])
    rec = Recorder({"v1/tickets": lambda r: httpx.Response(200, json=next(pages))})
    first = await _call(monkeypatch, rec, "gorelo_list_tickets", {})
    assert first["has_more"] is True and first["next_cursor"] == "page-2-token"
    second = await _call(monkeypatch, rec, "gorelo_list_tickets", {"cursor": first["next_cursor"]})
    assert second["tickets"] == [{"Id": "t-2"}] and second["has_more"] is False
    assert rec.calls("v1/tickets", "GET")[1].url.params["Cursor"] == "page-2-token"


async def test_get_ticket_unwraps_data(monkeypatch):
    """AC3/TC-GORELO-004."""
    rec = Recorder({"v1/tickets/t-42": ok_item({"Id": "t-42", "Title": "VPN down", "Description": "..."})})
    result = await _call(monkeypatch, rec, "gorelo_get_ticket", {"ticket_id": "t-42"})
    assert result == {"Id": "t-42", "Title": "VPN down", "Description": "..."}


@pytest.mark.parametrize(
    "tool,arg_name,path",
    [
        ("gorelo_get_ticket", "ticket_id", "v1/tickets/missing"),
        ("gorelo_get_client", "client_id", "v1/clients/999"),
        ("gorelo_get_contact", "contact_id", "v1/contacts/999"),
        ("gorelo_get_contract", "contract_id", "v1/contracts/999"),
        ("gorelo_get_agent_asset", "agent_asset_id", "v1/assets/agents/missing"),
    ],
)
async def test_get_unknown_id_returns_not_found(monkeypatch, tool, arg_name, path):
    """AC4/TC-GORELO-005."""
    arg_value = "999" if arg_name in ("client_id", "contact_id", "contract_id") else "missing"
    rec = Recorder({path: not_found()})
    args = {arg_name: int(arg_value) if arg_name in ("client_id", "contact_id", "contract_id") else arg_value}
    result = await _call(monkeypatch, rec, tool, args)
    assert result["error"]["code"] == "not_found"


async def test_add_comment_defaults_to_public(monkeypatch):
    """AC5/TC-GORELO-006."""
    rec = Recorder({"POST v1/tickets/t-1/comments": ok_item({"Id": "c-1"})})
    result = await _call(monkeypatch, rec, "gorelo_add_ticket_comment", {"ticket_id": "t-1", "body": "Rebooted the printer."})
    sent = body(rec.calls("v1/tickets/t-1/comments", "POST")[0])
    assert sent["ConversationTypeId"] == 1 and "ConversationId" not in sent
    assert result == {"Id": "c-1"}


async def test_add_comment_with_conversation_id_targets_side_conversation(monkeypatch):
    """AC5/TC-GORELO-007."""
    rec = Recorder({"POST v1/tickets/t-1/comments": ok_item({"Id": "c-2"})})
    await _call(monkeypatch, rec, "gorelo_add_ticket_comment", {"ticket_id": "t-1", "body": "Reply", "conversation_id": "conv-9"})
    sent = body(rec.calls("v1/tickets/t-1/comments", "POST")[0])
    assert sent["ConversationTypeId"] == 3 and sent["ConversationId"] == "conv-9"


async def test_create_ticket_required_fields(monkeypatch):
    """AC6/TC-GORELO-008."""
    rec = Recorder(
        _lookup_routes()
        | {
            "POST v1/tickets": ok_item({"Id": "t-new"}),
            "v1/tickets/t-new": ok_item({"Id": "t-new", "DisplayNumber": "T-100"}),
        }
    )
    args = {"title": "New issue", "client_id": 7, "status_name_or_id": "New", "type_name_or_id": "Incident", "group_id": 3}
    result = await _call(monkeypatch, rec, "gorelo_create_ticket", args)
    sent = body(rec.calls("v1/tickets", "POST")[0])
    assert sent == {"Title": "New issue", "ClientId": 7, "StatusId": 1, "TypeId": 10, "GroupId": 3}
    assert result == {"id": "t-new", "display_number": "T-100"}


async def test_create_ticket_missing_required_field_errors_without_calling_gorelo(monkeypatch):
    """AC6/TC-GORELO-009 (FastMCP's own required-argument check -> invalid_argument via EnvelopeFastMCP)."""
    rec = Recorder(_lookup_routes())
    for missing in ("title", "client_id", "status_name_or_id", "type_name_or_id", "group_id"):
        args = {"title": "x", "client_id": 7, "status_name_or_id": "New", "type_name_or_id": "Incident", "group_id": 3}
        del args[missing]
        result = await _call(monkeypatch, rec, "gorelo_create_ticket", args)
        assert result["error"]["code"] == "invalid_argument", missing
    assert not rec.calls("v1/tickets", "POST")


async def test_create_ticket_accepts_ids_directly_and_resolves_priority_source(monkeypatch):
    rec = Recorder(_lookup_routes() | {"POST v1/tickets": ok_item({"Id": "t-2"}), "v1/tickets/t-2": ok_item({"Id": "t-2", "DisplayNumber": "T-2"})})
    args = {
        "title": "x", "client_id": 7, "status_name_or_id": "1", "type_name_or_id": "10", "group_id": 3,
        "priority_name": "urgent", "source_name": "Email", "contact_id": 4, "description": "details",
    }
    await _call(monkeypatch, rec, "gorelo_create_ticket", args)
    sent = body(rec.calls("v1/tickets", "POST")[0])
    assert sent["PriorityId"] == 1 and sent["SourceId"] == 1 and sent["ContactId"] == 4 and sent["Description"] == "details"


# ---- clients / contacts / contracts ------------------------------------------


async def test_list_clients_contacts_contracts_no_filters(monkeypatch):
    """AC7/TC-GORELO-010."""
    rec = Recorder(
        {
            "v1/clients": ok_list([{"Id": 1, "Name": "Acme"}]),
            "v1/contacts": ok_list([{"Id": 2, "FirstName": "Ann"}]),
            "v1/contracts": ok_list([{"Id": 3, "Name": "Gold"}]),
        }
    )
    clients = await _call(monkeypatch, rec, "gorelo_list_clients", {})
    contacts = await _call(monkeypatch, rec, "gorelo_list_contacts", {})
    contracts = await _call(monkeypatch, rec, "gorelo_list_contracts", {})
    assert clients == {"clients": [{"Id": 1, "Name": "Acme"}], "has_more": False, "total_count": 1}
    assert contacts["contacts"] == [{"Id": 2, "FirstName": "Ann"}]
    assert contracts["contracts"] == [{"Id": 3, "Name": "Gold"}]


async def test_list_clients_query_filters(monkeypatch):
    """AC7/TC-GORELO-011."""
    rec = Recorder({"v1/clients": ok_list([{"Id": 1, "Name": "Example Co"}])})
    await _call(monkeypatch, rec, "gorelo_list_clients", {"query": "Example Co"})
    assert rec.calls("v1/clients")[0].url.params["Query"] == "Example Co"


async def test_get_client_and_contact(monkeypatch):
    rec = Recorder({"v1/clients/1": ok_item({"Id": 1, "Name": "Acme"}), "v1/contacts/2": ok_item({"Id": 2, "FirstName": "Ann"})})
    assert await _call(monkeypatch, rec, "gorelo_get_client", {"client_id": 1}) == {"Id": 1, "Name": "Acme"}
    assert await _call(monkeypatch, rec, "gorelo_get_contact", {"contact_id": 2}) == {"Id": 2, "FirstName": "Ann"}


async def test_get_contract(monkeypatch):
    rec = Recorder({"v1/contracts/3": ok_item({"Id": 3, "Name": "Gold"})})
    assert await _call(monkeypatch, rec, "gorelo_get_contract", {"contract_id": 3}) == {"Id": 3, "Name": "Gold"}


# ---- time entries -------------------------------------------------------------


async def test_list_time_entries_filtered_by_ticket(monkeypatch):
    """AC8/TC-GORELO-012."""
    rec = Recorder({"v1/time-entries": ok_list([{"Id": 1, "Ticket": {"Id": "t-1"}}])})
    result = await _call(monkeypatch, rec, "gorelo_list_time_entries", {"ticket_ids": "t-1"})
    assert rec.requests[0].url.params["TicketIds"] == "t-1"
    assert result["time_entries"] == [{"Id": 1, "Ticket": {"Id": "t-1"}}]


async def test_log_time_entry_with_actual_hours(monkeypatch):
    """AC9/TC-GORELO-013."""
    rec = Recorder({"POST v1/time-entries": ok_item({"Id": 55})})
    args = {"ticket_id": "t-1", "started_on": "2026-11-01T09:00:00Z", "actual_hours": 1.5}
    result = await _call(monkeypatch, rec, "gorelo_log_time_entry", args)
    sent = body(rec.calls("v1/time-entries", "POST")[0])
    assert sent == {"TicketId": "t-1", "StartedOn": "2026-11-01T09:00:00Z", "ActualHours": 1.5}
    assert result == {"Id": 55}


@pytest.mark.parametrize("extra", [{}, {"ended_on": "2026-11-01T10:00:00Z", "actual_hours": 1.0}])
async def test_log_time_entry_requires_exactly_one_duration(monkeypatch, extra):
    """AC9/TC-GORELO-014."""
    rec = Recorder()
    args = {"ticket_id": "t-1", "started_on": "2026-11-01T09:00:00Z"} | extra
    result = await _call(monkeypatch, rec, "gorelo_log_time_entry", args)
    assert result["error"]["code"] == "invalid_argument"
    assert not rec.calls("v1/time-entries", "POST")


# ---- assets ---------------------------------------------------------------


async def test_list_and_get_agent_assets(monkeypatch):
    """AC10/TC-GORELO-015."""
    rec = Recorder(
        {
            "v1/assets/agents": ok_list([{"Id": "a-1", "Name": "WIN-01"}]),
            "v1/assets/agents/a-1": ok_item({"Id": "a-1", "Name": "WIN-01", "Os": "Windows 11"}),
        }
    )
    listed = await _call(monkeypatch, rec, "gorelo_list_agent_assets", {})
    assert listed["agent_assets"] == [{"Id": "a-1", "Name": "WIN-01"}]
    got = await _call(monkeypatch, rec, "gorelo_get_agent_asset", {"agent_asset_id": "a-1"})
    assert got == {"Id": "a-1", "Name": "WIN-01", "Os": "Windows 11"}


# ---- reference lookups --------------------------------------------------------


async def test_list_ticket_statuses_and_types(monkeypatch):
    rec = Recorder(_lookup_routes())
    statuses = await _call(monkeypatch, rec, "gorelo_list_ticket_statuses", {})
    types = await _call(monkeypatch, rec, "gorelo_list_ticket_types", {})
    assert statuses == {"statuses": STATUSES}
    assert types == {"types": TYPES}
