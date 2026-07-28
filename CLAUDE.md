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
- Include screenshots of affected pages in the PR description. With a server
  running, `mise run shots -- / /events` saves PNGs to `screenshots/` (paths
  resolve against `localhost:8000`; wraps `aubx agent-browser`).
- Don't ignore lint rules globally.
- Use the `src/ludamus/adapters/web/django/templatetags/tessera` design system
  for UI; don't hand-roll components.
- Tailwind = component look. Partials in `templates/components/`;
  `extra_class` for page layout only. No utility copy-paste into CSS.
- For any user-facing UI work (pages, forms, tables, modals, empty/error states,
  copy), use the `product-design` skill (`.claude/skills/product-design/`)
  _before_ building — it routes to the component catalog, reachable-states
  checklist, Polish copy rules, and a verification checklist.
- No single-line files.
- Tailwind is here to lower CSS output size. Prefer Tailwind over CSS files.

## Definition of done

Strings wrapped + i18n updated; schema change has a reversible migration;
failure paths return useful errors, no silent swallows; keyboard-reachable
semantic HTML; new path logs meaningful events; authz checked, no new secrets;
happy path + one edge case tested.

## Debt metrics (tingle)

`tingle.toml` counts debt (suppression comments, `Any`, `request.di.uow`,
legacy LOC, …). `tingle stat --diff` / `tingle report --diff` show what your
branch adds vs `main`.

`tingle check` (in `mise run lint` / `check`) fails when the branch's metrics
grow on net — paying debt in one offsets taking it on in another. Read the
added occurrences it prints and remove what you can. A justified addition is
fine; say so in the PR. Don't game a counter to keep a number flat.

## Papercuts

Hit friction? Retried command, flaky tool, stale cache, bad error, gotcha. Log
it now: `mise run papercut -- <note>`. One or two sentences, what you did → what
got in the way.

## Architecture

GLIMPSE layers, bottom to top: `pacts` (protocols, DTOs, errors), `mills`
(logic, services), `links` (models, repos), `gates` (views, CLIs, APIs),
`inits` (DI). `specs` (business invariants, pure constants) sits beside
`pacts` and is imported only by `mills`. `edges` (settings, wsgi) stay
outside the import graph. `adapters/` is legacy.

Before writing backend code in these layers, load the `glimpse` skill
(`.claude/skills/glimpse/`). It has the import rules, file layout, slicing
vocabulary, and patterns. The map of this codebase (nouns, pages, models,
wiring examples) is in [docs/agents/architecture.md](docs/agents/architecture.md).

Access data: views call `request.services.<service_name>.<method>(...)` and get
back ready-to-render DTOs (Pydantic, never Django models). Services live in
`mills/`, take specific repo protocols + `TransactionProtocol` via the
constructor, and own transactional boundaries.

Legacy: some views still use `request.di.uow.<repo>` during the strangler-fig
migration. [docs/agents/services-migration.md](docs/agents/services-migration.md)
has the per-file recipe. New code must use `request.services`; never extend the
`request.di.uow` surface.

## Rules

- Functions/methods with 3+ parameters (excluding `self`) take them as
  keyword-only:

  ```python
  def fun(*, a: int, b: str, precision: int) -> int: ...
  ```

- Avoid docstrings. Code should be self-explanatory, and the
  Arrange-Act-Assert structure in tests obvious from the code itself.
- Test type follows the layer under test: `mills` gets unit tests; `gates`,
  `links`, `adapters.web`, and templates get integration tests. This holds
  when raising coverage too. Details and the pure-helper exception:
  [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md).
- View tests use `assert_response`, never manual assertions, and use ANY only
  for forms/views, never for simple values ([], {}, booleans, strings, ints).
  Patterns: [docs/agents/testing-assertions.md](docs/agents/testing-assertions.md).
- Migrating: UI belongs to Playwright. Assert status, redirect, context, and
  state in Python; assert rendered HTML in `tests/e2e`. Don't add
  `assert_response(contains=...)` on markup, and drop such assertions from
  tests you touch — the e2e run covers them, and the coverage reports combine.
- NEVER add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.
- `test` / `tested` is reserved for pytest; production names use `check` /
  `validation` / `verification`.
- Panel access proves you manage the current sphere/event, not the objects the
  request names. Scope every request-supplied id (URL pk/slug and body ids)
  to `current_event`/sphere before read or write. Do it in the service, not
  the view, and test that a foreign id 404/422s without side effects. See
  [panel object-scope authz](docs/refactors/panel-object-scope-authz.md).
- Keep `__init__.py` empty and import each symbol from the module that defines
  it. The allowed facade exceptions are listed in the `glimpse` skill.

## Translation conventions (Polish)

- **session** → "punkt programu" (except in "RPG session" → "sesja RPG")
- **track** → "blok" or "blok programowy"
- **facilitator** → "twórca programu"
- **time slot** → "przedział czasowy" (do **not** use "blok czasowy" — collides
  with the "track" translation)
- **proposal category** (prelekcja, sesja RPG, warsztaty, …) →
  "rodzaj atrakcji" on participant-facing pages (do **not** use "kategoria" —
  counterintuitive there); "kategoria" stays OK in the organizer panel

## Details

- [Architecture](docs/agents/architecture.md) — codebase map: nouns, pages,
  models, service wiring
- [GLIMPSE skill](.claude/skills/glimpse/SKILL.md) — layer, layout, and
  slicing rules
- [Services migration](docs/agents/services-migration.md) — per-file recipe for
  moving views from `request.di.uow` to `request.services`
- [Testing assertions](docs/agents/testing-assertions.md) — patterns for
  integration tests
- [Maintainer MCP server](docs/agents/mcp.md) — `/mcp/` endpoint, token auth,
  adding tools
- [Sandbox toolchain](docs/agents/sandbox.md) — fallbacks when the egress
  proxy blocks mise's GitHub downloads (Claude Code on the web)
- [URL conventions](docs/CODE_LAYOUT.md)
- [Testing strategy](docs/TESTING_STRATEGY.md)
