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
"""Name -> id resolution for ticket status/type/priority, shared by tools/tickets.py.

Gorelo exposes `GET /v1/tickets/statuses`, `/types` and `/priorities` as lookup
endpoints returning `{Id, Name}` pairs (fetched from the live OpenAPI document
2026-11-02) — unlike the design's initial assumption of a hardcoded 0-4 scale
with no lookup call, `/v1/tickets/priorities` exists and is used the same way
as statuses/types so a tenant's own display names resolve consistently.
"""

from typing import Any

from .api_client import GoreloClient


def _rows(payload: Any) -> list[dict]:
    data = payload.get("Data") if isinstance(payload, dict) else None
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def by_name(rows: list[dict], name: str, what: str) -> int:
    """Match ``name`` against a lookup list's `Name` field (case-insensitive).

    Raises ``ValueError`` naming the known values on a miss, so a tool that calls this
    turns an unmatched name into the standard `invalid_argument` envelope via `run_tool`.
    """
    for row in rows:
        if str(row.get("Name") or "").strip().lower() == name.strip().lower():
            return int(row["Id"])
    options = ", ".join(str(r.get("Name")) for r in rows[:30])
    raise ValueError(f"Unknown {what} {name!r}. Known values: {options}.")


def ids_by_names(rows: list[dict], names_csv: str, what: str) -> list[int]:
    """Comma-separated names -> ids; raises naming the known values on the first miss."""
    return [by_name(rows, name.strip(), what) for name in names_csv.split(",") if name.strip()]


async def status_rows(client: GoreloClient) -> list[dict]:
    return _rows(await client.get("v1/tickets/statuses"))


async def type_rows(client: GoreloClient) -> list[dict]:
    return _rows(await client.get("v1/tickets/types"))


async def priority_rows(client: GoreloClient) -> list[dict]:
    return _rows(await client.get("v1/tickets/priorities"))


async def source_rows(client: GoreloClient) -> list[dict]:
    return _rows(await client.get("v1/tickets/sources"))


def name_or_id_to_int(value: str, rows: list[dict], what: str) -> int:
    """Accept either a known id (as a string) or a name; tries numeric id first."""
    text = str(value).strip()
    if text.isdigit() and any(str(r.get("Id")) == text for r in rows):
        return int(text)
    return by_name(rows, text, what)
