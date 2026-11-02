# PRD-21211 · Code review

## Round 1 · 2026-11-02 · reviewed dev/PRD-21211 @ 7eb48dd (base main @ 97df62a)

Verdict: approved

Status: frozen @ 7eb48dd

### Scope

Full diff `97df62a...7eb48dd` (30 files, 4445 insertions): new `gorelo-mcp` first-version PSA
connector (17 tools across 6 modules: tickets, reference lookups, clients, contacts, contracts,
time entries, agent assets), tests, Dockerfile/compose, README, docs.

### Checks performed

- Independently re-ran the gate on the reviewed commit: `uv sync` clean, `uv run pytest -q` →
  `114 passed, 1 warning` (warning is the pre-existing pytest-asyncio/starlette deprecation notice,
  matches the `[DEV]` stub's claim exactly).
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no output (no
  Chinese anywhere in the repo).
- Manual secret scan (`gitleaks` binary not present on this machine either, same as dev's
  self-test) over `src/`, `tests/`, `README.md` for key/secret/token/password literals → none
  found; all credential examples in tests/README are placeholders.
- README "MSPbots Connector" section diffed byte-for-byte against
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` → identical.
- Read `src/gorelo_mcp/{server,api_client,config,_json,_lookups,_arguments,__main__}.py` and all
  of `tools/*.py` in full; read `tests/test_tools.py` and `tests/test_middleware.py` in full
  (`tests/test_api_client.py` spot-checked for the error-mapping and pagination cases it backs).
- Walked the SOP §14 delivery checklist section by section (contract, errors/network,
  container/deliverables, agent-facing design, logging/secrets, tests) against the code —
  see Findings for the one open item.

### Findings

No must-fix. Three observations, none blocking:

1. [suggestion] `src/gorelo_mcp/_lookups.py:33-43` (`by_name`) — the "known values" list in the
   `invalid_argument` message is capped at the first 30 rows with no "+N more" indicator. For a
   tenant with a large status/type list, the error could look like it enumerated everything when
   it did not. Low impact (Gorelo's own status/type/priority lists are typically small), cosmetic.
2. [suggestion] The tech design's Change list (`docs/tickets/PRD-21211.md` "Change list") calls
   for a standalone `src/gorelo_mcp/errors.py`; the implementation instead puts the envelope
   builder in `_json.py` and the status→code mapping in `api_client.py`. This is a technical-design
   detail dev is free to change (no user-visible behavior shifts, and the mapping/envelope are
   still in exactly one place each) — noted only so the design doc and the tree don't look
   inconsistent to the next reader.
3. [suggestion] `gitleaks` was unavailable on both the dev and review machines, so that §14/§11
   checklist line is unverified by tooling on this ticket (manual text scan substituted, see
   Checks performed). Not a new gap introduced by this change — same constraint every MCP ticket
   on this machine has hit — but worth someone eventually installing the binary in the shared
   environment.

### Verification against design

- AC1–AC13: each has at least one automated test (`tests/test_tools.py`, `tests/test_api_client.py`)
  and/or a middleware test; `tools/list` snapshot test pins the tool count (17) and required
  params, matching the Data & API contract table exactly.
- The three "Design corrections" the dev doc records (priority lookup endpoint exists; no
  status-name lookup for clients/contacts/contracts/assets — `status_ids` instead; ticket-comment
  `ConversationTypeId` must match the conversation kind) are each reflected consistently in the
  corresponding `tools/*.py` file and covered by a test — verified by reading the code, not just
  trusting the note.
- Credential handling matches the SOP's three operating-model rules: headers only
  (`server.py` `GatewayCredentialsMiddleware`), no shared state across requests (`contextvars`,
  reset in `finally`, concurrency-isolation test `test_concurrent_requests_do_not_share_credentials`),
  nothing persisted (`GoreloCredentials.__repr__` redacts the key, confirmed by
  `test_credentials_repr_hides_key`).
- `run_tool` (`tools/_common.py:79-106`) catches every exception path (`GoreloApiError`,
  `ValueError`, bare `Exception`) and always returns the structured envelope — AC4's "never an
  uncaught exception" is enforced in one place for all 17 tools, not per-tool.
- No destructive (DELETE) tools present, matching the stated non-goal.

### Fixes

N/A — no must-fix in Round 1.
