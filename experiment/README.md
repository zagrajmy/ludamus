# experiment/ — Zagrajmy on rat-stack + Foldkit

A rewrite experiment. The plan, decisions, layer map and conventions are in
[PLAN.md](PLAN.md); the measurements in [evals/REPORT.md](evals/REPORT.md).

```text
apps/
  web/        Foldkit application: features (pages), ui (tessera), client runtime,
              server entry (SSR flags loaders)
  server/     Node host: static assets, /rpc, /api, /mcp, then the Foldkit fetch handler
packages/
  capability/ rat-stack's defineContract/implement + projections (vendored)
  core/       contracts, schemas, ports, pure rules, capabilities (no IO)
  database/   effect/sql stores over the Django-owned SQLite/Postgres schema
  auth/       Django session bridge, CurrentUser
  i18n/       catalog from django.po, locale negotiation, t()
evals/        benchmark harness and results
```

Run it: see "Running" in PLAN.md. Everything is driven from the repo root's
`mise run experiment:*` tasks.
