# goblin-zagrajmy

Pi extension scaffolding for Goblin, the coding agent employee. One job: give
the agent the Zagrajmy MCP server as its only tool surface — the extension
discovers the server's tools at startup and registers one Pi tool per MCP
tool, so tool growth happens server-side (`docs/agents/mcp.md`) and never
here.

Design decisions live in [docs/agents/employees.md](../../docs/agents/employees.md).

## Status

Scaffolding only — typecheck-clean, not wired into any runtime or CI:

- `src/mcp-client.ts` — thin JSON-RPC client for the MCP streamable HTTP
  transport (initialize, tools/list, tools/call). No SDK dependency; the
  wire format is small enough to speak directly, which keeps the isolate
  bundle lean.
- `src/bridge.ts` — turns discovered MCP tools into Pi tool registrations.
- `src/types.ts` — structural types for the slice of Pi's extension API this
  package touches, stated locally until the real `@mariozechner/pi`
  dependency is added (Act I of the campaign plan). When it lands, these
  types get replaced by the package's own and any drift becomes a compile
  error.
- `src/config.ts` — environment contract. The token is read per call and
  never cached: in the target deployment the secrets-broker Actor injects
  short-lived credentials, so a cached value would just be a stale leak.

Tests are deferred until the Pi dependency pins the real API — asserting
against our own structural types would only test the mirror. Typecheck:

    npx tsc -p agents/goblin-zagrajmy
