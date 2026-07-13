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
  `extra_class` for page layout only. No utility copy-paste into CSS — CSS for
  what Tailwind can't (state, scroll, JS panels).
- For any user-facing UI work (pages, forms, tables, modals, empty/error states,
  copy), use the `product-design` skill (`.claude/skills/product-design/`)
  _before_ building — it routes to the component catalog, reachable-states
  checklist, Polish copy rules, and a verification checklist.
- No single-line files.

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

GLIMPSE system:

- `gates / adapters` (clis, apis, views)
- `links / adapters` (models, repos)
- `inits` (DI)
- `mills` (logic)
- `pacts` (protocols, DTOs, aggregates)
- `specs` (business invariants — pure constants, no IO, consumed only by mills)
- `edges` (infrastructure boundary modules)

Access data: views call `request.services.<service_name>.<method>(...)` and get
back ready-to-render DTOs (Pydantic, never Django models). Services live in
`mills/`, take specific repo protocols + `TransactionProtocol` via the
constructor, and own transactional boundaries.

Legacy: some views still use `request.di.uow.<repo>` during the strangler-fig
migration — see `docs/agents/architecture.md` and
`docs/agents/services-migration.md`. New code must use `request.services`; never
extend the `request.di.uow` surface.

## Layer

Edges are outside of the import system. They are not going to be imported
directly.

Relation `X -> Y` means (Y can import X). It is transitive and reflexive.

Relaxed rules:

`pacts` -> `mills` -> `links` -> `gates` -> `inits`

`specs` sits alongside `pacts` at the bottom but is imported only by `mills`:
`pacts` -> `specs` -> `mills` (specs forbidden in links, gates, inits)

Strict rules:

- `(anything) -> inits -> (nothing) (top level)`
- `mills -> gates | links | inits`
- `pacts -> (anything) (bottom level)`
- `specs -> links | gates | inits` (forbidden)

## Rules

- Views return DTOs to templates, never models
- A class that implements a `Protocol` must declare it as a base class, so the
  intent is explicit and the type checker verifies conformance. Exception: very
  generic protocols (e.g. `TransactionProtocol`, structural callbacks) where
  multiple unrelated implementations exist by duck-typing.
- Functions/methods with 3+ parameters (excluding `self`) must take them as
  keyword-only with `*,`:

  ```python
  def fun(a: int, b: str) -> int: ...
  def method(self, a: int, b: str) -> int: ...
  def fun(*, a: int, b: str, precision: int) -> int: ...
  ```

- Avoid docstrings unless absolutely unavoidable. Code should be
  self-explanatory; the Arrange-Act-Assert structure in tests should be obvious
  from the code itself. Docstrings are stale the day they're committed. Keep
  them to the bare minimum.
- Test type follows the layer of the code under test: `mills` → unit tests;
  `gates` / `links` / `adapters.web` / templates → integration tests. This holds
  when raising coverage too — an uncovered line in `gates` / `links` means a
  missing **integration** test, never a quick mock-everything unit test of
  IO-bearing code (views, repos, importers). Exception: pure IO-free helper
  functions (e.g. template-tag filters) may be unit-tested wherever they live.
  See `docs/TESTING_STRATEGY.md`.
- Use `assert_response` utility for view tests, never manual assertions
- In tests, NEVER use ANY for simple values ([], {}, booleans, strings, ints).
  Use ANY only for forms/views. See docs/agents/testing-assertions.md.
- NEVER add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.
- Default: do not write re-export `__init__.py` files (no wildcard imports, no
  explicit re-export lists). Keep `__init__.py` empty and import each symbol
  from the module that defines it (`from ludamus.foo.bar import Bar`, not
  `from ludamus.foo import Bar`). Allowed exceptions:
  - **Framework / public-API package** — when the package is consumed by
    external code and the inner module layout is implementation detail, a facade
    `__init__.py` is appropriate.
  - **Line-length pressure** — if the canonical import path is too long to fit
    the line-length limit, expose a shorter facade. Treat this the same as
    splitting a file or method that has grown too big: a pragmatic response when
    the symptom appears, not a blanket allowance.
  - **Pre-existing legacy-module facade** — `<layer>/__init__.py` wildcarding
    `<layer>/legacy.py` (mills, pacts, inits) stays as is.

## Translation conventions (Polish)

- **session** → "punkt programu" (except in "RPG session" → "sesja RPG")
- **track** → "blok" or "blok programowy"
- **facilitator** → "twórca programu"
- **time slot** → "przedział czasowy" (do **not** use "blok czasowy" — collides
  with the "track" translation)

## Details

- [Architecture](docs/agents/architecture.md) — layers, repos, services
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
