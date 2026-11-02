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
"""Shared types, cursor-paging / envelope helpers and the error-handling wrapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import GoreloApiError, GoreloClient
from ..config import MAX_PAGE_SIZE

logger = logging.getLogger("gorelo_mcp.tools")

ClientFactory = Callable[[], GoreloClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured",
    "Gorelo credentials are missing for this request (X-Gorelo-Api-Key and X-Gorelo-Region).",
    False,
)

Limit = Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]
Cursor = Annotated[str | None, Field(description="Opaque cursor from a prior page's next_cursor; omit for the first page.")]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None and v != ""}


def paging(limit: int, cursor: str | None) -> dict[str, Any]:
    return compact({"PageSize": limit, "Cursor": cursor})


def data(payload: Any) -> Any:
    """The `Data` member of Gorelo's {IsSuccess, StatusCode, Data, DataContext, Notifications} envelope."""
    if isinstance(payload, dict) and "Data" in payload:
        return payload["Data"]
    return payload


def page_cursor(payload: Any, item_key: str) -> dict:
    """Shape a cursor-paged Gorelo list response as {<item_key>, has_more, next_cursor, total_count}."""
    rows = data(payload)
    rows = rows if isinstance(rows, list) else ([] if rows is None else [rows])
    pagination = {}
    if isinstance(payload, dict):
        context = payload.get("DataContext")
        if isinstance(context, dict):
            pagination = context.get("Pagination") or {}
    return compact(
        {
            item_key: rows,
            "has_more": bool(pagination.get("HasMore")),
            "next_cursor": pagination.get("NextCursor"),
            "total_count": pagination.get("TotalCount"),
        }
    )


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[GoreloClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        value = await action(client)
    except GoreloApiError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if value is None:
        value = {"done": True}
    return value if isinstance(value, str) else dump_json_capped(value)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
