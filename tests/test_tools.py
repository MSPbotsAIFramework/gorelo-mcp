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
"""tools/list snapshot, annotations, and error-envelope mapping (TC-GORELO-017/019). No network access."""

import asyncio
import json

import pytest

from gorelo_mcp.api_client import GoreloApiError
from gorelo_mcp.server import INSTRUCTIONS, create_mcp_server

# Tool names and required params are a public contract: existing agents and
# tenant connections depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "gorelo_list_tickets": set(),
    "gorelo_get_ticket": {"ticket_id"},
    "gorelo_list_ticket_comments": {"ticket_id"},
    "gorelo_list_ticket_statuses": set(),
    "gorelo_list_ticket_types": set(),
    "gorelo_create_ticket": {"title", "client_id", "status_name_or_id", "type_name_or_id", "group_id"},
    "gorelo_add_ticket_comment": {"ticket_id", "body"},
    "gorelo_list_clients": set(),
    "gorelo_get_client": {"client_id"},
    "gorelo_list_contacts": set(),
    "gorelo_get_contact": {"contact_id"},
    "gorelo_list_contracts": set(),
    "gorelo_get_contract": {"contract_id"},
    "gorelo_list_time_entries": set(),
    "gorelo_log_time_entry": {"ticket_id", "started_on"},
    "gorelo_list_agent_assets": set(),
    "gorelo_get_agent_asset": {"agent_asset_id"},
}
WRITE_TOOLS = {"gorelo_create_ticket", "gorelo_add_ticket_comment", "gorelo_log_time_entry"}
PAGED_LIST_TOOLS = {
    "gorelo_list_tickets", "gorelo_list_ticket_comments", "gorelo_list_clients",
    "gorelo_list_contacts", "gorelo_list_contracts", "gorelo_list_time_entries", "gorelo_list_agent_assets",
}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    """TC-GORELO-019: tools/list returns exactly the 17 tools in the design's table."""
    assert set(tools) == set(EXPECTED_TOOLS)
    assert len(tools) == 17


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    """TC-GORELO-019: description <=500 chars, first line <=100 chars."""
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    """TC-GORELO-019: readOnlyHint/destructiveHint set per the write/read split."""
    annotations = tools[name].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is (name not in WRITE_TOOLS)
    assert not annotations.destructiveHint


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly ask" in tools[name].description


@pytest.mark.parametrize("name", sorted(PAGED_LIST_TOOLS))
def test_paged_lists_cap_limit_at_200(tools, name):
    limit = tools[name].inputSchema["properties"]["limit"]
    assert limit["maximum"] == 200
    assert limit["default"] == 50


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500
    assert "\n" in INSTRUCTIONS
    for entity in ("tickets", "clients", "contacts", "contracts", "time", "asset"):
        assert entity in INSTRUCTIONS.lower()


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (409, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    """TC-GORELO-017: Gorelo HTTP status -> {code, retryable} mapping table."""
    envelope = json.loads(GoreloApiError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    """AC11: every tool answers not_configured when called without credentials in context."""
    content, _ = asyncio.run(create_mcp_server().call_tool("gorelo_list_tickets", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
