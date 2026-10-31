# Agent law for experiment/

This directory is a child project of [rat-stack](https://ratstack.sh).
rat-stack's [AGENTS.md](https://ratstack.sh/AGENTS.md) is the law; this file
is the day-one replacement of its project-specific sections. For a non-trivial
task start with rat-stack's `rat-stack-mode` skill: read the matching
playbooks (`add-a-capability`, `add-a-store`, `query-design`,
`test-behaviour`, `uncomplect`, `keep-or-cut`) before writing, and report which
rules changed which choices. Search them through the `rat-stack` MCP server in
the repo's `.mcp.json` or `https://ratstack.sh/llms-full.txt`.

The product rules of Zagrajmy itself (UX, Polish copy, accessibility, the
enrollment invariants) stay in the repo root's `CLAUDE.md`, `PRODUCT.md` and
`docs/`. The experiment's plan, decisions and conventions are in
[PLAN.md](PLAN.md); deviations from rat-stack are logged in
[docs/ratstack-conformance.md](docs/ratstack-conformance.md).

## Project law

- One contract, every surface. `defineContract` in
  `packages/core/src/contracts.ts`, `implement` beside the data it needs,
  registered once in `capabilities`. `/rpc`, `/api`, `/mcp` are projections
  from `packages/capability`; no hand-rolled route, tool or RPC.
- Schemas are the contract: input, output and failure are Effect `Schema`;
  OpenAPI and MCP declarations are derived.
- Django owns the database schema for the whole strangler-fig period
  (PLAN.md D2). Stores mirror its tables, decode every row, bound every
  read, and never write outside a capability.
- The Playwright suite in `../tests/e2e` is the acceptance bar and must not be
  edited to pass. Seed data comes only from `../tests/e2e/scripts`.
- Tests: properties for rules, models for history, Scenes for UI, one example
  per seam; `it.effect`/`it.layer`, never `Effect.run*` or
  `ManagedRuntime.make` in a test. Plant a bug before trusting a test.
- No comments in code except `SAFETY:` above a type assertion and a reason
  after `--` on a directive. Every override names its rule.
- Strings people read go through `@zagrajmy/i18n`; English msgids match
  `django.po`.

## Bugs found in the Django app

Porting is an audit. When work here shows the Django app is wrong (a rule
the port cannot reproduce without reproducing a defect, a differential case
that exposes an unhandled input, a query that disagrees with the model), it is
not fixed here. Record it in `docs/ratstack-conformance.md` under "Django
bugs" with the evidence, and the coordinator spins out a small fix PR against
`main` (test first, torment-nexus review, merge on green). Agents report;
they do not open those PRs.

## Architecture

- Dependency direction: `apps/server` and `apps/web/src/server` →
  `packages/{database,auth,i18n}` → `packages/core` → `packages/capability` →
  Effect. Browser code (`apps/web/src/{client,features,ui}`) imports only
  `@zagrajmy/core/contracts`, `@zagrajmy/capability/rpc-group` and
  `@zagrajmy/i18n`.
- Core owns ports (`packages/core/src/ports`), schemas, pure rules and
  capabilities. `packages/database` and `packages/auth` are adapters.
- Pages: `apps/web/src/client/<page>/` (program) and
  `apps/web/src/features/<page>/` (view); flags loaders in
  `apps/web/src/server/pages/`. See PLAN.md "Page architecture".
- Projections are instantiated in one module of `apps/server`.

## Commands

```sh
pnpm install                  # exact pins, lockfile is authoritative
pnpm check                    # typecheck + lint + format
pnpm test                     # vitest across the workspace
pnpm build                    # tsc builds and the Foldkit vite build
mise run experiment:e2e -- <spec>   # from the repo root
mise run experiment:evals           # from the repo root
```

## Boundaries and sign-off

- Safe: adding a capability and wiring it; new or tightened tests; docs;
  tightening lint; anything under `evals/`.
- Needs the owner: adding or changing a dependency pin (list every one in the
  PR), loosening `oxlint.config.ts` or `tsconfig.base.json`, editing the
  Playwright specs or the Django app, writing to the seeded database outside
  the app.
- Never: `git --no-verify`, force-pushing, secrets in the tree.
