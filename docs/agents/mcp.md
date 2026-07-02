# Maintainer MCP server

Zagrajmy exposes a maintainer-only [MCP](https://modelcontextprotocol.io)
server over HTTP, so AI agents (Claude Code, Cursor, Executor, …) can operate
the platform through the same services the views use, never around them.

## Access

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
- Organizer and attendee tiers come later, on the same registry: scope-tagged
  tools and a separate endpoint per trust level. An endpoint loads only the
  tools of its tier, so the security boundary is filtering at wiring time
  rather than per-call policy checks.
- WebMCP also comes later. Once the W3C `navigator.modelContext` API
  stabilizes, annotate existing forms (declarative API) so in-browser agents
  act in the user's own session, reusing the same tool definitions over a
  different transport.
- Keep the surface small. If it ever grows large, expose search over tools
  instead of dumping the whole catalog into agent context.

## Adding a tool

1. Subclass `Tool[YourInput]` in `gates/mcp/tools.py`: pydantic input model
   (field descriptions become the client-facing schema), `name`,
   `description`, and a `handle()` that calls a service and returns DTO JSON
   (`model_dump_json` / `TypeAdapter.dump_json`).
2. Register it in `build_registry()`.
3. Add integration tests in `tests/integration/web/mcp/` (tools/list order and
   a tools/call case).

Domain errors need no new plumbing: `NotFoundError` and invalid arguments
already map to MCP `isError` results, and unknown tools to JSON-RPC errors.
