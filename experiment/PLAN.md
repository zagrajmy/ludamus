# Zagrajmy on rat-stack: the experiment plan

This directory is a rewrite experiment: the same product (Ludamus/Zagrajmy,
the Django app one level up) rebuilt on [rat-stack](https://ratstack.sh)
with the UI in [Foldkit](https://foldkit.dev). The question it answers is
"is this a good way forward for the codebase?", and the only honest way to
answer it is to build a real slice, run the real acceptance suite against it,
and measure.

## What counts as done

1. The slice below passes the **existing** Playwright specs that cover it,
   unmodified, run against the new server (`mise run experiment:e2e`).
2. `mise run experiment:evals` produces `evals/REPORT.md`: old vs new on the
   same seeded database and the same machine. Numbers are whatever they are.
3. `pnpm check && pnpm test` is green in `experiment/`.

The Python unit and integration tests cannot run against TypeScript; they
exercise Django internals. The Playwright suite is the cross-implementation
contract, and `tests/e2e/scripts/bootstrap_*.py` remain the single source of
seed data. Where a pure rule was ported (enrollment seat selection, enrollment
windows, proposal rules), the Python property tests export generated cases to
JSON and the TypeScript port replays them, so the two implementations are held
to the same examples.

## Decisions

- **D1 Scope is a vertical slice.** 83k lines of Python, 292 routes and 572
  e2e cases do not fit one session. The slice is the public read path, the
  enrollment and proposal flows, and the core of the organiser panel. The
  e2e matrix reports every spec, in scope or not, so coverage is visible.
- **D2 One database, Django owns the schema.** The new app reads and writes
  the SQLite file `tests/e2e` seeds (`dev.e2e.sqlite3`). Store schemas mirror
  the Django tables (`db_table` names, snake_case columns). This is also the
  strangler-fig story in production: both apps can run against one Postgres
  while pages move over. Migrations would move to Drizzle only after cutover,
  so there is no Drizzle schema here.
- **D3 Node host, not Workers, for the experiment.** rat-stack deploys to
  Cloudflare via Alchemy. The Playwright suite needs a server on
  `localhost:8000` next to a SQLite file, so `apps/server` is a Node
  composition root. The Foldkit server entry is a Web `fetch` handler either
  way, so it is the same artifact Workers would run; `apps/infra` holds the
  Alchemy stack sketch, unexecuted.
- **D4 Auth bridges Django sessions.** The e2e suite signs in with Django's
  `sessionid` cookie. `packages/auth` verifies Django's signed, zlib-compressed
  session payload (HMAC-SHA256, salt `django.contrib.sessions.SessionStore`)
  and the per-user session auth hash, then loads the user. No Better Auth in
  the slice; the Auth0 callback is out of scope.
- **D5 SSR first, hydrate for interactivity, full navigations between pages.**
  Every page is server-rendered from `Flags` computed per request (the
  capabilities run in-process). Links between pages are full loads, like
  the Django app, so redirects, titles and `waitForURL` behave identically.
  In-page state (modal, filters, tabs, `?view=`, `?session=`) lives in the
  Foldkit Model and syncs to the URL with `Navigation.pushUrl`/`replaceUrl`.
  Mutations (enroll, submit a proposal, panel CRUD) go through the contracts
  projected to RPC (`toRpcGroup`) at `/rpc`; the same contracts project to
  HTTP (`/api`, `/openapi.json`) and MCP (`/mcp`) for free.
- **D6 Same design system.** The Tailwind theme, tokens and component CSS of
  `src/ludamus/client` are reused; the tessera component templates are
  ported to Foldkit view functions in `apps/web/src/ui`. Specs assert roles,
  labels, text and a few `data-*` hooks, so those must match exactly.
- **D7 i18n comes from `django.po`.** `packages/i18n` builds its catalog from
  `src/ludamus/locale/pl/LC_MESSAGES/django.po` (msgid English, msgstr
  Polish), negotiates the locale from `Accept-Language` like Django's
  `LocaleMiddleware` (default `pl`), and exposes a typed `t`.
- **D8 Pins follow rat-stack.** Effect 4.0.7, Foldkit 0.169.0 with the
  template's `@foldkit/vite-plugin` patch and peer allowances. `@foldkit/node`
  wants Effect 4.1, so the Node host is ours (60 lines, mirrors it).
- **D9 rat-stack's fence, minus what needs its site.** oxlint with the
  template's plugins (no comments, no module-level mutable state, boundaries,
  anti-slop), oxfmt, `tsc --strict` with the base tsconfig. `effect-tsrs` and
  tsgo diagnostics are not wired yet.
- **D10 rat-stack is the reference; deviations are listed, not hidden.**
  [AGENTS.md](https://ratstack.sh/AGENTS.md) is the law we build against,
  its skills are the playbooks (`add-a-capability`, `add-a-store`,
  `query-design`, `test-behaviour`, `rat-stack-mode`), and
  [docs/ratstack-conformance.md](docs/ratstack-conformance.md) records every
  place this experiment or the Django app breaks a rule, with the reason.
  The MCP server at `https://ratstack.sh/mcp` (`.mcp.json`, `rat-stack`) and
  `https://ratstack.sh/llms-full.txt` are the search surfaces; read the owning
  rule and skill before changing code.

## Layer map (GLIMPSE → rat-stack)

| Django (GLIMPSE)                    | Here                                                                 |
| ----------------------------------- | -------------------------------------------------------------------- |
| `pacts` protocols, DTOs, errors     | `packages/core/src/<noun>/*.ts` Schemas, `ports/*.ts` services, `Schema.TaggedError`s |
| `specs` pure invariants             | `packages/core/src/<noun>/rules.ts` pure functions, property-tested  |
| `mills` services                    | `packages/core/src/<noun>/*-capability.ts` via `defineContract` + `implement`, depending only on ports |
| `links` repositories                | `packages/database/src/<noun>-store.ts` Layers implementing the ports over `effect/sql` |
| `gates` views, templates, client ts | `apps/web/src/features/<page>/` (Foldkit Model/Message/update/view), `apps/web/src/ui/` (tessera), `apps/web/src/server/pages/<page>.ts` (Flags loaders) |
| `inits` DI                          | `apps/server/src/main.ts` host and `apps/web/src/server/runtime.ts` |
| templates `base.html` chrome        | `apps/web/src/features/shell/`                                       |
| management commands                 | `apps/cli` (not in the slice)                                        |

Boundary rules (lint-enforced where rat-stack's plugins reach): browser code
(`apps/web/src/client`, `apps/web/src/features`, `apps/web/src/ui`) imports
contracts and schemas from `@zagrajmy/core`, never stores, never
`@zagrajmy/database` or `@zagrajmy/auth`. Server code lives under
`apps/web/src/server` and `apps/server`.

## Page architecture

`Flags` is `{ shell, page }`. `shell` is what `base.html` knew: sphere,
viewer, locale, nav, flash messages. `page` is a tagged union, one case per
page, holding exactly the data that page's template got in its context.

Each page follows rat-stack's web feature blueprint, split in two:

- `apps/web/src/client/<page>/` owns the Foldkit program: `Flags` (Schema,
  what the server computes for this page), `Model` (Schema), `init(flags,
  url)`, `Message`, `update`, and named `Command.define` definitions
  (verb-first, `EnrollInSession`; result messages past tense,
  `SucceededEnroll`, `FailedEnroll`). Remote state lives in the Model as
  Foldkit `AsyncData`.
- `apps/web/src/features/<page>/` is the thin view: it reads the Model and
  sends Messages. No transport, retries or startup in a view.

One send follows one path: feature → Message → `update` → Command →
`RpcClient` over the contract's `toRpcGroup` → capability → store. Browser
modules import only `@zagrajmy/core/contracts` and
`@zagrajmy/capability/rpc-group` from those packages; every schema a view
needs is exported from `contracts.ts`.

The server side is `apps/web/src/server/pages/<page>.ts`: `load(request
context) => Effect<PageFlags, PageError>`, calling capability handlers
directly (same process, no HTTP). `apps/web/src/server/router.ts` maps
URL → loader and HTTP status (404 for `NotFound`, 302 for redirects via
`Server.Responded`).

URLs are identical to the Django app's. Specs navigate by path.

## Slice and owners

| Area                              | e2e specs that are the acceptance tests                                                                                                                                                                                                                                                            |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shell, feed, static pages         | `feed-cards`, `unlisted-events`, `page-title`, `footer-license`, `content-pages`, `theme-color`, `sphere-logo`, `about`, `landing` (hero and links only)                                                                                                                                                                    |
| Event page                        | `event-details`, `event-hero`, `event-time`, `event-description`, `event-filters`, `event-multiselect`, `event-schedule-views`, `event-schedule-folding`, `event-schedule-rail`, `event-slot-headers`, `session-tags-cloud`, `seat-label`, `event-location-crumbs`, `event-propose-entry`, `link-preview`, `proposal-status-badge`, `markdown-sanitising`, `worst-case` |
| Enrollment                        | `enroll-states.auth`, `waiting-list.auth`, `promotion.auth`, `enrollment-banner.auth`, `resign-after-close.auth`, `session-bookmark-signed-out.auth`, `signup-age.auth`, `party-refusals.auth`, `party-companion.auth`                                                                                   |
| Proposal wizard                   | `anonymous-proposal`, `dynamic-fields`, `write-in-fields`, `proposal-duration`, `proposal-form-layout`, `uncategorized-proposal`, `propose-reuse.auth`, `discord-proposal.auth`                                                                                                                             |
| Panel core                        | `panel`, `panel-crud`, `panel-tracks`, `proposal-cards`, `proposal-status-filter`, `proposal-delete-restore`, `proposal-accept`, `cover-images`                                                                                                                                                             |

Out of the slice (reported in the matrix as not implemented): timetable and
confirmations, maps, print and konwencik export, encounters, board, profile,
guilds, sphere team, notifications, dashboard, design page, MCP OAuth, CSP
nonce policy, consent banner analytics.

## Waves

1. Foundations, in parallel: i18n; tessera UI kit and shell; database stores
   for the slice's nouns; RPC/HTTP/MCP projections, request context and the
   e2e harness; the pure domain port with property and differential tests.
2. Pages, in parallel, each owning its spec files above.
3. Evals, report, PR.

## Running

```sh
mise run test:e2e:prep          # seeds dev.e2e.sqlite3 and the auth states (Django)
cd experiment && pnpm install && pnpm build
mise run experiment:serve       # Node host on :8000 against the seeded DB
mise run experiment:e2e -- event-details.spec.ts   # existing specs, new server
mise run experiment:evals       # old vs new benchmarks → evals/REPORT.md
```

Environment (`.env.schema`): `DATABASE_PATH`, `SECRET_KEY` (must equal
Django's, `e2e-secret-key` for the seed), `PORT`, `PUBLIC_ORIGIN`.

## Conventions for contributors (human or agent)

- Read `node_modules/effect/AGENTS.md` before writing Effect code (rat-stack's
  source-first rule); it ships with the pinned version.
- No comments except `SAFETY:` above a type assertion and a reason after `--`
  on a lint directive. Names carry the meaning.
- Functions with 3+ parameters take one options object. Never type a
  parameter as `object` or `unknown` (anti-slop `no-object-parameters`,
  `no-unknown-parameters`): parse external input with Schema at the boundary
  and pass the parsed type.
- A service is a `Context.Service` class whose `make` captures its
  dependencies so its methods carry no requirements, with `static layer`
  beside it in the same file (`packages/core/src/file-inspector.ts` in the
  template). Config is a service too (`AppConfig` mirrors `.env.schema`),
  not `Config.String` calls scattered through stores.
- Stores decode input before issuing statements, bound every read with an
  explicit limit, and distinguish invalid input from storage failure
  (`add-a-store`, `query-design`): constant round trips per capability,
  batched `IN` reads, no query in a loop over rows.
- Every row read from SQL is decoded with a Schema. Every error is a
  `Schema.TaggedError` with a `message` getter. No `any`, no `as` without
  `SAFETY:`.
- `Effect.fn("Name.method")(function* name() {...})` for every effectful
  function so spans carry names.
- Contracts live in `packages/core/src/contracts.ts`; `Rpc.make`, `HttpApi*`,
  `Tool.make` appear only inside `packages/capability`; projections are
  instantiated in one module of the composition root.
- Views are pure. Side effects are Commands. Model is a Schema struct.
- Message names: UI intent in past tense (`ClickedEnroll`, `ChangedFilter`),
  Command results `Succeeded…`/`Failed…`.
- Strings shown to people go through `t`. English msgids are the keys and
  must match `django.po` msgids where the Django template had one.
- Reproduce the Django markup's roles, labels, headings and `data-*` hooks
  that specs read; do not reproduce its class names unless the tessera
  component already has them.
- Tests: `*.story.test.ts` (update), `*.scene.test.ts` (view), `*.test.ts`
  (capabilities with `@effect/vitest` against a read-only copy of the seeded
  DB). A domain rule is an `it.prop`; anything with history is a model test;
  one example per seam. `it.effect`/`it.layer` only, never `Effect.run*` or
  `ManagedRuntime.make` in a test. Plant a bug and watch the test fail before
  trusting it. Write the failure modes down first. Playwright is the
  acceptance bar.
