# Maintainer MCP server

Zagrajmy exposes a maintainer-only [MCP](https://modelcontextprotocol.io)
server over HTTP, so AI agents (Claude Code, Cursor, Executor, …) can operate
the platform through the same services the views use, never around them.

## Access

### OAuth (any MCP client)

Add the endpoint URL to any MCP client; no token to paste:

```bash
claude mcp add --transport http zagrajmy https://<domain>/mcp/
claude mcp add --transport http zagrajmy-org https://<sphere-domain>/mcp/organizer/
```

The client gets a 401 whose `WWW-Authenticate` header points at
`/.well-known/oauth-protected-resource/mcp/` (or `.../mcp/organizer/`), which
names this site as the authorization server
(`/.well-known/oauth-authorization-server`). The client then opens
`/mcp/oauth/authorize/` in the browser. The user logs in and approves the
client on a consent page. Organizers also pick the event the token may
write. The client swaps the code at `/mcp/oauth/token/` for
the same signed token the pages below mint.

Clients identify themselves with a
[Client ID Metadata Document](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/)
(CIMD): the `client_id` is an HTTPS URL whose JSON lists the client's
`redirect_uris`. No registration and no allowlist. The consent page shows
the metadata host next to the self-declared name. Only public clients with
PKCE S256 are accepted. Dynamic Client Registration is deprecated in the
MCP spec and not offered. Codes live 60 seconds in the shared cache and
redeem once. There are no refresh tokens: after 30 days the client runs the
flow again.

The metadata fetch (`links/client_metadata.py`) goes to a URL a stranger
chose, so it resolves the host first and refuses non-public addresses. It
also follows no redirects, times out after 5 s, and caps the body at 5 KB.

### Manual token

1. Log in on the deployed site with a Django **superuser** account.
2. Open `/mcp/token/` and generate a token (shown once, valid 30 days).
3. Connect a client to `/mcp/` with the token as a Bearer header:

   ```bash
   claude mcp add --transport http zagrajmy https://<domain>/mcp/ \
     --header "Authorization: Bearer <token>"
   ```

   Or add the URL as a remote MCP source in Executor and set the same header.

Tokens are Django-signed values (no DB table): they embed the user id and are
re-checked against the database on every request, so the token works only
while the account stays an active superuser. Revoke by clearing the superuser
flag in Django admin; rotate everything by changing `SECRET_KEY`.

### Organizer tier

Sphere managers mint a token from the **MCP access** tab on an event's
settings (`/panel/event/<slug>/settings/mcp/`). Create the event in the
panel first — `create_event` is maintainer-only.

Tokens embed `(user_id, sphere_id, event_id)`:

- **Read** can see the whole sphere (sibling events, announcements, programme
  of another event in the sphere).
- **Write** always targets the token's event. Write tools do not take
  `event_id` from the client.

Every request re-checks `is_manager` and that the event still belongs to the
sphere. The endpoint loads only organizer-scoped tools, so maintainer tools
are structurally unreachable from it. Old tokens that omit `event_id` fail
auth.

The organizer tier provides programme verbs for spaces, time slots, tracks,
sessions, and venue maps, with writes scoped to one event per token and
sphere-wide reads.

## Architecture

The MCP gate follows GLIMPSE. It is a transport, not an agent: the app has no
model and no LLM dependency, and makes no decisions on its own.

<!-- markdownlint-disable MD013 -->

| Piece | Location | Role |
| ----- | -------- | ---- |
| Tool registry | `gates/mcp/registry.py` | `Tool` base (pydantic input → JSON text output) + `ToolRegistry` |
| Tool set | `gates/mcp/tools.py` | Hand-curated maintainer tools over `ServicesProtocol` |
| Protocol | `gates/mcp/protocol.py` | Stateless JSON-RPC subset of MCP Streamable HTTP |
| HTTP gate | `gates/web/django/mcp/views.py` | Bearer auth, JSON parsing, `/mcp/token/` mint page |
| OAuth gate | `gates/web/django/mcp/oauth.py` | Discovery metadata, consent page, code-for-token exchange |
| OAuth service | `mills/mcp.py` | CIMD client checks, redirect URI matching, PKCE, single-use codes |

<!-- markdownlint-enable MD013 -->

Tools call `request.services.<service>` exactly like views, so business
invariants and transactions hold for MCP callers. Every tool is written by
hand as a considered maintainer operation; we do not auto-export service
methods.

## Roadmap (decided, not yet built)

Decisions from the WebMCP/Executor design discussion (July 2026), so they
don't get re-derived or contradicted:

- The maintainer tier comes first (this implementation). No agent lives in
  the app: the app is a tool server, and agents run in maintainers' own MCP
  clients. [Executor](https://github.com/RhysSullivan/executor) is the
  recommended client-side control plane (catalog, policy, pause-for-approval,
  audit).
- The attendee tier comes later on the same registry: scope-tagged tools and
  a separate endpoint per trust level, so the security boundary stays
  filtering at wiring time rather than per-call policy checks.
- WebMCP also comes later. Once the W3C `navigator.modelContext` API
  stabilizes, annotate existing forms (declarative API) so in-browser agents
  act in the user's own session, reusing the same tool definitions over a
  different transport.
- Keep the surface small. If it ever grows large, expose search over tools
  instead of dumping the whole catalog into agent context.

## Programme batches

Organizer clients can keep the singular `create_session` and `assign_session`
operations for interactive edits. Imports should use `create_sessions` and
`assign_sessions`, each accepting up to 250 items per call. Batch results stay
in input order and report failures per item; successful items remain committed.
`create_sessions` is safe to retry because `source_row_id` is event-scoped and
idempotent. Retrying an identical assignment is a no-op.

The [POLCON 2026 programme sync runbook](polcon26-programme-sync.md) documents
one monitored spreadsheet import, including dry-run review and retry limits.

## Konwencik styles

Organizer tokens can read and patch their event's existing Konwencik exports:

- `get_konwencik_settings` takes no arguments. It returns integration IDs,
  current settings, and named track/category/session-field IDs; `[]` when no
  export is configured. Connection credentials and sheet configuration are
  not returned.
- `update_konwencik_styles` takes `integration_id`, optional `track_colors`
  (`{"42": "#203b50"}`), and optional `category_icons`
  (`{"17": "fa.gamepad"}`). Keys are primary keys from the read tool.
  Only supplied entries change; an empty string removes that override.
  Foreign IDs and internal tracks reject the whole patch.

Updates preserve unmentioned styles, override fields, sync settings, and the
export lock. Neither tool starts an export; an enabled automatic sync picks up
the styles on its next run. No integration creation or sync-toggle tool.

## Adding a tool

1. Subclass `Tool[YourInput]` in `gates/mcp/tools.py` — or, for an organizer
   programme verb, `gates/mcp/programme_tools.py`: pydantic input model
   (field descriptions become the client-facing schema), `name`,
   `description`, a `scope` (`ToolScope` from `pacts/mcp.py` — the endpoint
   loads only its tier's tools), and a `handle(call)` that reads
   `call.services` / `call.data` / `call.actor` and returns DTO JSON
   (`model_dump_json` / `TypeAdapter.dump_json`).
2. Add it to `_all_tools()`.
3. Add integration tests in `tests/integration/web/mcp/` (tools/list order and
   a tools/call case).

Domain errors need no new plumbing: `NotFoundError` and invalid arguments
already map to MCP `isError` results, and unknown tools to JSON-RPC errors.

Every `tools/call` is audit-logged. Sensitive fields must be redacted before
they reach the log; batch tools record only item counts and correlation IDs.
Do not add a tool whose arguments carry personal data without extending that
sanitization first.
