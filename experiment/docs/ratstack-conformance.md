# rat-stack conformance log

rat-stack's [AGENTS.md](https://ratstack.sh/AGENTS.md) is the law this experiment builds against. This file records where code breaks it: the experiment's own code, and the Django app it rewrites where the rule is one rat-stack would apply to any product. Each entry names the rule, the place, and whether it is a deliberate deviation (kept, with the reason) or debt (to fix). Entries leave this file only when the code changes.

## Deliberate deviations in the experiment

| Rule (source) | Where | Why we deviate |
| --- | --- | --- |
| Lifecycles are machines: finite modes, retries and cancellation live in XState machines under `createEffectActor` | The enrollment seat lifecycle (waiting → offered → confirmed/expired) is pure functions plus stores, no XState | The slice ports Django's existing decision logic one-to-one so the differential tests hold it to Python. The participation status machine is the natural first XState machine; it is listed as the next step in PLAN.md rather than done here. |
| `effect-tsrs --strict --type-check` and the Effect language-service diagnostics fail `check` | `pnpm check` runs plain `tsc --strict` plus oxlint | Not wired yet; `@effect/tsgo` and `@yielded/effect-tsrs` pins are known. The floating-Effect class of bugs is therefore not caught by the fence in this experiment. |
| Deploy with Alchemy to Cloudflare Workers; `Cloudflare.Website.Foldkit` | `apps/server` is a Node host; `apps/infra` is an unexecuted sketch | The acceptance suite needs `localhost:8000` next to a SQLite file (PLAN.md D3). The server entry is the same `fetch.js` a Worker would run. |
| `add-a-store`: schemas, Drizzle migrations and vendor resources travel together | `packages/database` has no migrations; Django owns the schema | PLAN.md D2: one database shared with Django during the strangler-fig period. Stores still decode rows, bound reads and separate invalid input from storage failure. |
| Auth is the Better Auth cartridge providing `CurrentPerson` to RPC | `packages/auth` verifies Django's `sessionid` instead | The Playwright suite signs in with Django session cookies; a second identity store would break the one-database decision. |
| Every finite public page is prerendered (`prerenderPaths`) | Nothing is prerendered | Every page in the slice depends on the request (sphere from Host, viewer from cookie, live seat counts). Content pages (`/about/`, terms, privacy) could be prerendered per sphere; not done. |
| `@foldkit/node` hosts a built Foldkit app | A 60-line host in `apps/server` | `@foldkit/node` 0.2.0 peers on Effect 4.1; rat-stack pins 4.0.7. |
| Pins and dependency changes need owner sign-off | The experiment adds packages the template does not have (Tailwind, sqlite) | The owner asked for the rewrite; every added pin is listed in the PR summary for sign-off in review. |
| Per-request identity reaches every surface (rat-stack: `CurrentPersonMiddleware` on RPC) | `/mcp` in `apps/server/src/surfaces.ts` | `McpServer.layerHttp` runs tool handlers on its own fiber, without the HTTP request, so `/mcp` serves the sphere of `PUBLIC_ORIGIN` as an anonymous caller behind a static `MCP_TOKEN` bearer. Tools whose contract needs a signed-in user die with `SignInRequired`. Per-token identity (Django's OAuth MCP) is the follow-up. |

## Debt in the experiment (to fix before the PR leaves draft)

| Rule | Where | Fix |
| --- | --- | --- |
| `nodeBuiltinImport` diagnostic | `packages/auth/src/django-signing.ts` imports `node:crypto`, `node:zlib`, `node:buffer` | Keep behind a `DjangoSigning` service with a Node Layer, or a targeted `@effect-diagnostics-next-line` with reason. |
| Browser modules import only `@zagrajmy/core/contracts` | `apps/web/src/features/events-feed.ts` imports `EventSummary` from `@zagrajmy/core` | Re-export view schemas from `contracts.ts`; import from there. |
| Strings shown to people go through `t` | `apps/web/src/features/app.ts` ("Log in", "Events", "Not found") | Use `@zagrajmy/i18n` once it lands. |
| Parse values at the boundary with Schema; no `as` | `evals/benchmarks/pageweight.ts`, `auth.ts`, `report.ts` use `JSON.parse` and `as` | Decode with Schema; benchmark scripts are covered by the root `tsconfig.json` and lint. |

| Config is a supplied, validated dependency (`AppConfig`)             | `apps/web/src/server/request-context.ts` reads `Config.Int("SITE_ID")` directly                               | Move `SITE_ID` into `AppConfig` and take it from there.                                                            |
| Name the system of record; no duplicate stores for one fact           | `packages/database/src/{feed,shell,landing}-store.ts` overlap `EventStore.listForFeed`, `EncounterStore`, `AnnouncementStore` | Consolidate the feed, shell and landing loaders onto the noun stores; delete the three page-shaped stores.         |
| The fence: `eslint(no-redeclare)` rejects a schema and its type sharing a name | 166 sites across core, database, web use `export const X = Schema…; export type X = typeof X.Type`          | Owner decision: rename schemas the way rat-stack does (`XSchema` + `type X`) or scope the rule off for TS files. Renaming conforms; the rule has no declaration-merge option. |
| Remaining targeted lint rules after the mechanical pass               | ~250 findings: `no-unsafe-*` (41/29/27), `prefer-named-capture-group` (29), `require-unicode-regexp` (18), Foldkit route-string and submodel-payload rules, `no-manual-tag-comparison` | Fix per area in the wave-2 lint pass; keep the counts in this row current.                                          |

## Rules the Django app breaks (would apply to any product)

Observed while porting; not changed here.

| Rule | Where in `src/ludamus` | Note |
| --- | --- | --- |
| No comments: names, types and tests carry the meaning | Throughout (`CLAUDE.md` allows `NOTE:`/`SAFETY:`/`HACK:`/`TODO:` prefixes; many templates and views carry narrative comments) | A policy difference, not a defect; the repo's own rule already limits comments to what code cannot express. |
| Errors are part of the interface: name the failure and fail at the boundary | `adapters/web/django/views.py` enrollment flow reports overflow through flash messages built inside the view | The rewrite moves these to `Schema.TaggedError`s returned by the capability and rendered by the view. |
| One capability, every surface: the MCP server projects the same handlers as the UI | `gates/mcp` hand-writes MCP tools beside the views they mirror | In the experiment `/mcp`, `/api` and `/rpc` project one `capabilities` tuple. |
| Lifecycles are machines | `SessionParticipation.status` transitions are spread over `views.py`, `mills/enrollment.py` and sweeps | Same remark as the experiment's deviation above; the Bend models in `formal/enrollment` are the current substitute. |
| Errors are part of the interface; keep boundary words honest | `links/db/django/models.py` `conflicted_user_ids` (line 1245) | The query matches another session whose start or end falls inside this one, so a confirmed seat in a session that wholly contains this one (starts before, ends after) is not a conflict, while `AgendaItem.overlaps_with` says it is. The comment above the query claims it never misses a genuine conflict. Found by the TypeScript port's property tests; confirmed by reading the query, not yet reproduced against Django. |
| Failures keep their meaning: a decode failure is a typed refusal, not a 500 | `pacts/durations.py` duration parsing on import review | `str.isdigit()` accepts superscript digits such as `²`, then `int()` raises a plain `ValueError` the review view does not catch. Found while porting; not reproduced in the browser. |
| Bound every read | Several list views page in Python after an unbounded query (checked: proposals and facilitators panel lists) | Worth confirming per view before acting; noted from reading the repositories, not measured. |

## Django bugs found here → offshoot PRs

Every defect in the Django app that this work uncovers gets its own small PR
against `main`, test first, reviewed with torment-nexus and merged on green.

| Bug | Found by | Offshoot PR |
| --- | --- | --- |
| `conflicted_user_ids` misses a session that wholly contains the candidate | enrollment port property tests | in progress (branch `fix/enrollment-conflict-containment-and-duration-digits`) |
| Duration parser accepts `isdigit()` characters `int()` rejects, so `²` becomes a 500 on import review | differential export of `pacts/durations.py` | same PR |
| Promotion charges a pass for a waiter already seated in the event (documented open finding, reproduced by the port as an expected failure) | VERIFICATION.md open finding; `enrollment/` port | merged: #1644 |
| Offered/held seat passes the conflict check; two enrolls double-book; allowance race (documented open findings) | VERIFICATION.md; `enrollment/README.md` | in progress: plan 021 (`plans/021-enrollment-row-locking.md`), branch `fix/enrollment-row-locking` |
| `audit-deps` red on `main`: pyasn1 0.6.4 and follow-redirects 1.16.1 advisories | CI of the fix PRs | merged: #1645 |

