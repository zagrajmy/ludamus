# CLAUDE.md

Django event management. Python 3.14, Poetry, mise.

## Commands

```bash
mise run start      # dev server :8000
mise run test       # all tests
mise run check      # format + lint
mise run dj <cmd>   # django-admin
mise tasks          # list all tasks with descriptions
```

## Workflow

- Consider UX: Are we torturing the user? Can something be done in a more
  respectful or straightforward way? e.g:
  - is the info we're showing redundant?
  - are we asking for needless clicks? like showing a form with one selectable
    option?
- Use agent-browser to take screenshots of affected pages and include
  before/after images in the PR description
- NEVER modify, create, or delete non-TypeScript configuration files without
  explicit per-case approval.

<python>

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

</python>

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
- [URL conventions](docs/CODE_LAYOUT.md)
- [Testing strategy](docs/TESTING_STRATEGY.md)
