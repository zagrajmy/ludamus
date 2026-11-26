# CLAUDE.md

Django event management. Python 3.14, Poetry, mise.

## Commands

`mise tasks` is the source of truth for every runnable task and its
description — run it rather than trusting a hardcoded list here. Most used:
`mise run start`, `mise run test:py`, `mise run check`, `mise run dj <cmd>`.

## Workflow

- Consider UX: Are we torturing the user? Can something be done in a more
  respectful or straightforward way? e.g:
  - is the info we're showing redundant?
  - are we asking for needless clicks? like showing a form with one selectable
    option?
  - does each control hold one kind of thing? a switcher switches between
    layouts of the same set, a filter narrows the set, a sort reorders it —
    a filter sitting among the view tabs is a type error, and so is a
    control offering one option.
  - UIs have types. a tag cloud wraps tokens that already carry their
    kind; a definition list stacks named groups. restacking a cloud into
    ragged rows is that same type error.
- Include screenshots of affected pages in the PR description. With a server
  running, `mise run shots -- / /events` saves PNGs to `screenshots/` (paths
  resolve against `localhost:8000`; wraps `aubx agent-browser`). In a sandbox,
  publish with `/here-now` and link URLs.
- Don't ignore lint rules globally.
- No redundant migrations: if something can be done with a settings toggle or a
  single MCP call, it does not require a migration.
- Migration conflict with `main`: renumber the branch's own migrations on top
  of main's leaf, in order, and re-point the first one's `dependencies` to
  that leaf. Drop the branch's merge migrations. Never rename, renumber, or
  edit a migration already on `main`.
- `django.po` conflict? `mise run messages-resolve`; hand-fix only what it
  flags.
- Use the `src/ludamus/gates/web/django/templatetags/tessera` design system
  for UI; don't hand-roll components.
- Tailwind = component look. Partials in `templates/components/`;
  `extra_class` for page layout only. No utility copy-paste into CSS.
- User-facing UI work (pages, forms, tables, modals, empty/error states, copy)
  starts with the `product-design` skill (`.claude/skills/product-design/`).
- No single-line files.
- Tailwind is here to lower CSS output size. Prefer Tailwind over CSS files.

## Definition of done

Strings wrapped + i18n updated; schema change has a reversible migration;
failure paths return useful errors, no silent swallows; keyboard-reachable
semantic HTML; new path logs meaningful events; authz checked, no new secrets;
happy path + one edge case tested.

## Debt metrics (tingle)

`tingle.toml` counts debt (suppression comments, `Any`, legacy and
old-subdomain files, …). `tingle stat --diff` /
`tingle report --diff` show what your branch adds vs `main`.

`tingle check` (`mise run lint:tingle`; `mise run check` does not run it)
fails when the branch's metrics grow on net — paying debt in one offsets
taking it on in another. Read the added occurrences it prints and remove what
you can. A justified addition is fine; say so in the PR. Don't game a counter
to keep a number flat.

## Frontend debt (fallow)

`mise run lint:fallow` (in `mise run lint`) fails on frontend dead code,
duplication or complexity beyond `src/ludamus/client/fallow-baselines/`. Fix
what it names rather than re-baselining; after paying findings down, run
`mise run fallow:baseline` so they cannot come back. A new Vite input outside
`src/*.ts` also goes in `entry` in `src/ludamus/client/.fallowrc.json`.

## Friction (Frog)

Hit friction? Retried command, flaky tool, stale cache, bad error, gotcha.
Check `mise run frog -- list`, then log it with `mise run frog -- log`.
One or two sentences: what you did → what got in the way.
[Usage and resolution](.agents/friction-log/README.md).

## Architecture

GLIMPSE layers, bottom to top: `pacts` (protocols, DTOs, errors), `mills`
(logic, services), `links` (models, repos), `gates` (views, CLIs, APIs),
`inits` (DI). `specs` (business invariants, pure constants) sits beside
`pacts` and is imported only by `mills`. `edges` (settings, wsgi) stay
outside the import graph.

Before writing backend code in these layers, load the `glimpse` skill. It is
the `glimpse@glimpse` plugin; install steps in
[docs/LOCAL_DEV.md](docs/LOCAL_DEV.md). It has the import rules, file layout,
slicing vocabulary, and patterns. The map of this codebase (nouns, pages, models,
wiring examples) is in [docs/agents/architecture.md](docs/agents/architecture.md).

Access data: views call `request.services.<service_name>.<method>(...)` and get
back ready-to-render DTOs (Pydantic, never Django models). Services live in
`mills/`, take specific repo protocols + `TransactionProtocol` via the
constructor, and own transactional boundaries.

## Testing

- Never write unit tests after you write code.
- Highly prefer E2E tests as the sole testing mechanism. Use them to verify
  complex features work. At the end of E2E tests, produce a verifiable and
  repeatable artifact.
- E2E tests check behaviour through what assistive tech sees: roles, accessible
  names, labels, focus and ARIA state, not CSS selectors or ids. They take no
  `page.screenshot`; screenshots belong in the PR description.
- Never run the whole E2E suite locally: it takes most of an hour. Run only
  the specs you added or changed, plus the specs that cover the pages,
  templates, or client code you touched (grep `tests/e2e/tests` for the URL,
  role, or copy):
  `mise run test:e2e -- tests/<name>.spec.ts --project=chromium`. CI runs
  the full suite; say in the PR which specs you ran.
- Python test helpers arrange or assert, never act: the call under test
  stays in the test body. No `if` in a helper; write explicit functions and
  extract what they share. Build complicated objects with builder or factory
  classes. Shared helper modules are fine. Details:
  [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md).
- If you must test a system in isolation, first write down all the ways it
  could fail, then write the code.
- Tautological tests considered harmful: a test that restates the code it
  checks always passes and catches nothing.
- Change-detector tests considered harmful: a test that breaks on every
  refactor without a behavior change (asserting call sequences, mock
  arguments, field-by-field mapping) costs more than it guards.

## Rules

- Room overlap is supported, not advised. Organizers may put two sessions
  in one space at overlapping times. `accept_session` and `assign_session`
  must not refuse that write (`RoomBookingConflict`, not a
  `PlacementRejection` and not an application error). The existing
  booking-conflict UI — timetable conflict panel and problems page,
  `ConflictType.SPACE_OVERLAP` — is the warning. Do not add a new warning,
  and do not "fix" this by refusing the booking. The participant schedule
  and the printed timetable show both sessions side by side in the room.
- Functions/methods with 3+ parameters (excluding `self`) take them as
  keyword-only:

  ```python
  def fun(*, a: int, b: str, precision: int) -> int: ...
  ```

- Comments are exception: only what code cannot express. Else rename or
  split. Prefix: `NOTE:` outside constraint, `SAFETY:` hazard, `HACK:`
  deliberate deviation, `TODO:` known gap, issue link. No narration, no
  summaries, no work history microblogging.
- `gates`, `links`, and templates get integration tests when they need a
  Python test at all. Never raise coverage with a mock-everything
  unit test. Details: [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md).
- View tests use `assert_response`, never manual assertions, and use ANY only
  for forms/views, never for simple values ([], {}, booleans, strings, ints).
  Patterns: [docs/agents/testing-assertions.md](docs/agents/testing-assertions.md).
- Migrating: UI belongs to Playwright. Assert status, redirect, context, and
  state in Python; assert rendered HTML in `tests/e2e`. Don't add
  `assert_response(contains=...)` on markup, and drop such assertions from
  tests you touch — the e2e run covers them, and the coverage reports combine.
- Don't add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.
- `test` / `tested` is reserved for pytest; production names use `check` /
  `validation` / `verification`.
- Panel access proves you manage the current sphere/event, not the objects the
  request names. Scope every request-supplied id (URL pk/slug and body ids)
  to `current_event`/sphere before read or write. Do it in the service, not
  the view, and test that a foreign id 404/422s without side effects.
- Keep `__init__.py` empty and import each symbol from the module that defines
  it. The allowed facade exceptions are listed in the `glimpse` skill.
- Client IP comes only from `get_client_ip` in `gates/web/django/helpers.py`.
  Production sits behind Cloudflare, so `REMOTE_ADDR` and `X-Forwarded-For`
  name the proxy; the helper reads `CF-Connecting-IP`. Never read those
  headers directly. Topology in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Details

- [Maintainer MCP server](docs/agents/mcp.md) — `/mcp/` endpoint, token auth,
  adding tools
- [Production troubleshooting](docs/agents/troubleshooting.md) — PostHog and
  Cloudflare MCP triage. In Claude web sandboxes `.mcp.json` servers stay
  unauthenticated; use the claude.ai PostHog and Cloudflare connectors,
  which are already set up. The `zagrajmy-cloudflare`/`zagrajmy-posthog`
  auth warnings there are expected — don't report them.
- [Sandbox toolchain](docs/agents/sandbox.md) — fallbacks when the egress
  proxy blocks mise's GitHub downloads (Claude Code on the web)
- [URL conventions](docs/CODE_LAYOUT.md)
- [Moderation](docs/agents/moderation.md) — notices, chat reports, staff
  decisions, statements of reasons, police and UKE requests
- [Verification](docs/VERIFICATION.md) — Hypothesis/CrossHair properties, Bend
  models, the differential test and Bombadil: which layer each covers
