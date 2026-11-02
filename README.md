# Gorelo MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Gorelo](https://gorelo.io) Public API,
the combined PSA/RMM platform. It lets an AI agent read and act on service desk tickets, clients,
contacts, billing contracts, time entries and the managed-device (RMM) asset inventory.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Gorelo-Api-Key` | Yes | string | none | - | A Gorelo API key (Settings → Integrations → cog icon → Generate New Key). Sent upstream as `X-API-Key`. Scoped keys that lack access to an endpoint get Gorelo's own `403`, surfaced as `unauthorized`. | `your-api-key` |
| `X-Gorelo-Region` | Yes | string | none | `us`, `au` (case-insensitive) | Selects the regional API host: `us` → `https://api.usw.gorelo.io`, `au` → `https://api.aue.gorelo.io`. Any other value is a 401 naming the two accepted values. | `us` |

A request to `/mcp` missing either header, or with an `X-Gorelo-Region` outside `us`/`au`, gets
HTTP 401 naming what is wrong. Unresolved `${...}` placeholders count as missing.

## Tools

All tools return a JSON string. List tools take `limit` (page size, default 50, max 200 — Gorelo
rejects an out-of-range value rather than clamping it) and `cursor` (opaque, from a prior page's
`next_cursor`) and return `{<items>, has_more, next_cursor, total_count}`. **write** marks tools
that change data.

| Area | Tools |
|---|---|
| Tickets | `gorelo_list_tickets` (query, status_names, priority_names, type_names, client_ids, contact_ids, lead_assignee_ids, updated/created since/before), `gorelo_get_ticket` (**ticket_id**), `gorelo_list_ticket_comments` (**ticket_id**, conversation_type, conversation_id); **write**: `gorelo_create_ticket` (**title**, **client_id**, **status_name_or_id**, **type_name_or_id**, **group_id**, description, contact_id, priority_name, source_name), `gorelo_add_ticket_comment` (**ticket_id**, **body**, conversation_id) |
| Reference | `gorelo_list_ticket_statuses`, `gorelo_list_ticket_types` (no args — resolve the tenant-specific ids `status_names`/`type_names` and `gorelo_create_ticket` need; priority is a fixed `none`/`urgent`/`high`/`normal`/`low` scale, no lookup call needed) |
| Clients | `gorelo_list_clients` (query, status_ids, group_ids, updated/created since/before), `gorelo_get_client` (**client_id**) |
| Contacts | `gorelo_list_contacts` (query, client_ids, status_ids, updated/created since/before), `gorelo_get_contact` (**contact_id**) |
| Contracts | `gorelo_list_contracts` (query, client_ids, status_ids), `gorelo_get_contract` (**contract_id**) |
| Time | `gorelo_list_time_entries` (client_ids, ticket_ids, user_ids, started_since/before); **write**: `gorelo_log_time_entry` (**ticket_id**, **started_on**, **ended_on or actual_hours**, comment, billable_status, user_id) |
| Assets | `gorelo_list_agent_assets` (query, client_ids, status_ids), `gorelo_get_agent_asset` (**agent_asset_id**) |

Naming follows `gorelo_<verb>_<resource>`. Bold parameters are required. `status_ids`/`group_ids`
etc. are comma-separated lists; pass the numeric id shown on a record (clients, contacts, contracts
and assets have no vendor-published status-name lookup, unlike tickets).

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "unauthorized", "message": "Gorelo returned HTTP 403 for GET v1/tickets: Insufficient scope (code 070103)", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Gorelo can also answer HTTP 200 with `IsSuccess: false` and a
non-empty `Notifications` array; that is reported as an error too. Reads are retried with backoff
on 429, 5xx and network errors; writes only on 429.

## Run locally

```bash
uv sync
uv run python -m gorelo_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t gorelo-mcp:dev .
docker run --rm -p 8080:8080 gorelo-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). Credentials are never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Gorelo-Api-Key: your-api-key" \
  -H "X-Gorelo-Region: us" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# open tickets for a client
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Gorelo-Api-Key: your-api-key" \
  -H "X-Gorelo-Region: us" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"gorelo_list_tickets","arguments":{"client_ids":"7","status_names":"New,In Progress","limit":20}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **First version (17 tools, PRD-21211).** Built clean-room against Gorelo's own public OpenAPI
  document (`GET /swagger/v1/swagger.json` on either regional host; fetched 2026-11-02, OpenAPI
  3.0.4, 105 paths / 174 operations). Scope: service desk tickets (read, create, comment), status/
  type reference lookups, clients, contacts, billing contracts, time entries (read and log), and
  the managed-device asset inventory. No destructive (delete) tools in v1. Billing write
  operations (invoices/payments/product catalog), documents, forms, projects, organization
  (users/roles/API keys) and alerts are out of scope — straightforward additions later against the
  same OpenAPI document, not included here because this ticket named no specific need for them.
- **Cursor pagination, not offset.** Gorelo's own API pages with an opaque `Cursor`/`PageSize`
  pair (`DataContext.Pagination.{NextCursor,HasMore,TotalCount}`), unlike `kaseya-bms-mcp`'s
  `top`/`skip`. Tools here surface `cursor`/`next_cursor`/`has_more` to match Gorelo's own
  mechanism rather than emulating an offset, which would need server-side state.
- **Priority has a real lookup after all.** The design assumed ticket priority was a fixed 0-4
  scale with no lookup call needed; `GET /v1/tickets/priorities` turned out to exist on the live
  spec and is used the same way as `/statuses` and `/types` so a tenant's own display names
  resolve consistently — the write side (`CreateTicketCommand.PriorityId`) is still the same fixed
  enum (`None`=0, `Urgent`=1, `High`=2, `Normal`=3, `Low`=4).
- **No status-name lookup for clients, contacts, contracts or assets.** Verified against the live
  OpenAPI document: unlike tickets, Gorelo publishes no `/statuses` endpoint for these four areas
  — each record's `Status` is just an `{Id, Name}` pair with nothing to resolve a name against. So
  their list tools take `status_ids` (numeric), not `status_names`.
- **Ticket comments: Public and Side Conversation only.** `gorelo_add_ticket_comment` posts to the
  ticket's Public thread (`ConversationTypeId: 1`) by default, or into an existing side
  conversation (`3`) when `conversation_id` is given. Private (`2`) and Approval (`4`) conversations
  are out of scope for this tool — Approval in particular needs a separate create-approval flow
  this ticket did not ask for.
- **`gorelo_create_ticket` returns a display number by one extra read.** Gorelo's own
  `POST /v1/tickets` only returns the new ticket's `Id` (a uuid); the tool fetches the ticket once
  more immediately after creating it to return `display_number` alongside `id`, matching what an
  agent actually wants to reference the ticket by.
- **No test account during development.** Development and testing used mocked Gorelo HTTP
  responses (`httpx.MockTransport`, matching `kaseya-bms-mcp`'s own test pattern — no new mocking
  library added) plus a live `tools/list` and `tools/call` smoke test against Gorelo's real API
  with a placeholder key, which correctly returned `unauthorized` end to end. A real-account
  integration pass (`TC-GORELO-022`) is recorded as outstanding, not a blocker, per SOP.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
