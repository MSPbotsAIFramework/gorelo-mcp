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
"""Async client for the Gorelo Public API (OpenAPI 3.0.4, fetched 2026-11-02).

Every list/get response is shaped ``{IsSuccess, StatusCode, Data, DataContext,
Notifications}``; list endpoints carry cursor paging at
``DataContext.Pagination`` (``NextCursor``/``PreviousCursor``/``HasMore``/
``HasPrevious``/``TotalCount``). A 2xx response with ``IsSuccess: false`` and a
non-empty ``Notifications`` array is an error too (AC12/TC-GORELO-018), not
only a non-2xx HTTP status.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from ._json import error_envelope
from .config import REGION_HOSTS

logger = logging.getLogger("gorelo_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 20.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0

# One connection pool for the process. It never holds credentials: the
# X-API-Key header is set per request from the caller's own key.
_shared_http_client: httpx.AsyncClient | None = None


class _RejectAllCookies(DefaultCookiePolicy):
    """Never store or send a cookie: the HTTP client is shared by every tenant."""

    def set_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False

    def return_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False


def _no_cookies() -> CookieJar:
    # A plain CookieJar: httpx uses it as is (an httpx.Cookies would be copied into a default jar).
    return CookieJar(policy=_RejectAllCookies())


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(cookies=_no_cookies(), timeout=_TIMEOUT)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout). This is the mapping table AC12 requires.
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    409: ("invalid_argument", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class GoreloApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Gorelo API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


@dataclass(frozen=True)
class GoreloCredentials:
    region: str  # "us" or "au"
    api_key: str

    def __repr__(self) -> str:  # never leak the key into logs or tracebacks
        return f"GoreloCredentials(region={self.region!r}, api_key=<redacted>)"


class GoreloClient:
    """Thin wrapper over the Gorelo Public API for one caller's API key."""

    def __init__(self, credentials: GoreloCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client
        self.region = credentials.region
        self.base_url = REGION_HOSTS[credentials.region]

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._credentials.api_key, "Accept": "application/json"}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None) -> Any:
        return await self.request("POST", path, body=body)

    async def request(self, method: str, path: str, params: dict[str, Any] | None = None, body: Any = None) -> Any:
        http = self._http or _get_shared_http_client()
        url = f"{self.base_url}/{path.lstrip('/')}"
        query = {k: _param_value(v) for k, v in (params or {}).items() if v is not None}
        headers = self._headers()
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: GoreloApiError | None = None
            try:
                kwargs: dict[str, Any] = {"params": query, "headers": headers}
                if body is not None:
                    kwargs["json"] = body
                resp = await http.request(method, url, **kwargs)
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, GoreloApiError(0, f"Timed out calling Gorelo ({method} {path})")
            except httpx.RequestError as e:
                status, error = 0, GoreloApiError(0, f"Network error calling Gorelo ({method} {path}): {type(e).__name__}")

            logger.info(
                "gorelo_api method=%s path=%s status=%s ms=%d attempt=%d",
                method, path, status, (time.monotonic() - t0) * 1000, attempt,
            )

            # 429 is refused before processing, so any method may retry it; other
            # failures are retried only for reads, so a write never runs twice.
            retryable = status == 429 or (method == "GET" and (status == 0 or status >= 500))
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                raise error
            assert resp is not None
            if resp.status_code >= 400:
                raise GoreloApiError(resp.status_code, _error_message(resp, method, path))
            if not resp.content or not resp.content.strip():
                return None
            try:
                payload = resp.json()
            except ValueError:
                return {"raw_response": resp.text[:2000]}
            # Gorelo can answer HTTP 200 with IsSuccess: false and a non-empty
            # Notifications array (AC12/TC-GORELO-018) — that is an error too.
            if isinstance(payload, dict) and payload.get("IsSuccess") is False and payload.get("Notifications"):
                fallback = f"Gorelo rejected the request for {method} {path}"
                detail = _notifications_text(payload.get("Notifications"))
                raise GoreloApiError(400, f"{fallback}: {detail}" if detail else fallback)
            return payload


def _param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _notifications_text(notifications: Any) -> str:
    if not isinstance(notifications, list) or not notifications:
        return ""
    parts = []
    for item in notifications[:5]:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        message = item.get("Message") or "Unknown error"
        code = item.get("Code")
        parts.append(f"{message} (code {code})" if code else message)
    return "; ".join(parts)


def _error_message(resp: httpx.Response, method: str, path: str) -> str:
    fallback = f"Gorelo returned HTTP {resp.status_code} for {method} {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.lower().startswith("<"):
            return fallback  # an HTML error page, not useful to the agent
        return f"{fallback}: {text[:300]}" if text else fallback
    if isinstance(payload, dict):
        detail = _notifications_text(payload.get("Notifications"))
        if detail:
            return f"{fallback}: {detail}"
        message = payload.get("message") or payload.get("title") or payload.get("Message")
        if message:
            return f"{fallback}: {str(message)[:500]}"
    return fallback
