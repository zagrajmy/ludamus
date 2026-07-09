# GLIMPSE Architecture Reference

## Layers

```text
pacts   Protocols, DTOs, errors, enums, TypedDicts. Depends on nothing.
specs   Business invariants (pure constants, no IO). Only for mills.
mills   Business logic, services. Depends on pacts + specs. No Django, no ORM.
links   Repositories, Storage, UoW, external clients. pacts + Django ORM.
gates   Views, forms, URLs, templatetags, CLI commands. Depends on pacts + mills.
inits   DI container, middleware. Wires links into gates.
edges   settings, wsgi/asgi, manage. Outside GLIMPSE.
```

Import rules enforced by `importlinter` (`pyproject.toml` →
`[tool.importlinter]`). No exceptions without explicit approval. `adapters/` is
legacy — new code goes into GLIMPSE layers.

## File layout

Every layer is a package (directory), never a single `.py` file. Minimum shapes:

```text
pacts/{subdomain}.py                    # or pacts/{subdomain}/{context}.py
mills/{subdomain}.py                    # or mills/{subdomain}/{context}.py
specs/{subdomain}.py
inits/{subdomain}.py
gates/{port}/{adapter}/{subdomain}.py   # or .../{subdomain}/{context}/...
links/{port}/{adapter}/{kind}.py            # while small (models.py, repositories.py)
links/{port}/{adapter}/{kind}/{module}.py   # when {kind} crosses threshold
links/{port}/{adapter}/__init__.py          # facade — re-exports the public surface
links/{port}/{adapter}.py                   # e.g. links/payment_api/stripe.py
```

Split a file at ~1000 lines or when two unrelated concerns cause merge friction.
Never create nested folders before files exist to fill them.

**`__init__.py` re-export policy.** Default: keep `__init__.py` empty and import
each symbol from the module that defines it (`from pkg.foo.bar import Bar`, not
`from pkg.foo import Bar`). A facade `__init__.py` that re-exports a public
surface is allowed only for: a framework or public-API package whose inner
layout is implementation detail (the `links` adapter facade), relief from
line-length pressure, or a pre-existing legacy facade. It is not the default.

## Slicing vocabulary

- **Port** — delivery mechanism named after the domain concept: `web`, `cli`,
  `db`, `payment_api`, `email`
- **Adapter** — specific technology implementing a port: `django`, `stripe`,
  `blik`, `sendgrid`. One port can have multiple adapters.
- **Subdomain** — broad business area (`auth`, `billing`, `content`)
- **Bounded context** — responsibility boundary with its own ubiquitous
  language. Two contexts can share `User` and mean different things.
- **Entity** — persistence-level concept: the unit a DTO + repository wraps.
  Conceptual, not a file-layout axis: `links` slices by **kind** (per-adapter —
  e.g. `models` / `repositories` for `db/django`), not by entity.

Subdomain contains bounded contexts. Bounded context depends on entities.

## Slicing rules

**pacts, mills, specs, inits — by subdomain, then bounded context.**

```text
pacts/{subdomain}.py                    # flat while subdomain is small
pacts/{subdomain}/{bounded_context}.py  # split when subdomain grows fat
mills/{subdomain}.py
mills/{subdomain}/{bounded_context}.py
specs/{subdomain}.py
inits/{subdomain}.py
```

Each pacts module holds all boundary contracts for that subdomain/context:
DTOs, write TypedDicts, protocols, errors. Split by domain concern, not by
technical kind — no `pacts/dtos.py`, `pacts/protocols.py`, or `pacts/repos/`
directories.

**Boundary vs core — where does it go?** Decide by what the code does. If it
*crosses a boundary* (data shapes moving between layers) it is a contract →
`pacts` (DTOs, protocols). If it *enforces business rules* (aggregates, value
objects, invariants) it is core → `mills`. DTOs stay in `pacts` even though
they feel like domain objects: repo protocols in `pacts` return them, so moving
them to `mills` would make `pacts → mills → pacts` circular. A DTO is a data
contract for a port, not a domain object.

**links — `{port}/{adapter}/{kind}`. gates — `{port}/{adapter}/{subdomain}`.**

```text
# Small (default)
links/{port}/{adapter}/
    __init__.py             # facade — public surface
    kind1.py
    kind2.py

# Promoted when a kind crosses ~1000 lines
links/{port}/{adapter}/
    __init__.py             # facade — unchanged public import path
    kind1/
        __init__.py
        part1.py
        part2.py
    kind2/
        __init__.py
        part1.py
        part2.py

links/payment_api/stripe.py         # external client: port/adapter, single file
gates/web/django/{subdomain}.py     # or .../{subdomain}/{context}/...
gates/cli/django/{subdomain}.py
```

The `kind` axis and the split philosophy are per-adapter — `db/django` is
not the universal template. For `db/django`, the kinds are `models`
(internal) and `repositories` (public, exposed through the facade and
consumed via the protocols in `pacts`); a `payment_api/stripe` adapter may
stay a single file, or split into transport / types / signer with no
internal-vs-public distinction. **Baseline across adapters: halve, don't
shard; arrange parts so they don't cause circular imports.** The public
face of any `links` adapter is whatever its facade re-exports — internal
modules stay internal. For `db/django` specifically, that means external
code does `from ludamus.links.db.django import SessionRepository` and
never reaches `models`.

Same technology can serve multiple ports: `db/django` and `web/django` are
separate adapters. Same port can have multiple adapters: `payment_api/stripe`
and `payment_api/blik` are interchangeable implementations.

**Symmetry rule:** `pacts/` ↔ `mills/` must mirror each other — both sliced by
subdomain/context. If one splits a subdomain into contexts, the other must too.

## Growing rules

**Default: start as small as possible. Split only when size or friction makes
the case for itself.** Premature splitting creates churn, bloats the import
graph, and makes the layout look complete before the requirements actually
demand it.

Concrete thresholds — none is a hard line, all are "watch for this":

- **~1000 lines per file** — split a file when it crosses this and the two
  halves are unrelated enough that they cause merge friction. A 1500-line file
  holding one tightly coupled service is fine; a 600-line file holding three
  independent services is not.
- **~12 public symbols per namespace level** — applies to repository
  registries, the services tree, pacts subdomain modules, and the inits
  namespaces. At 13+ leaves, introduce a sub-bucket grouped by subdomain or
  bounded context. With ≤12, stay flat.
- **Folder must contain at least 2 files before it exists.** Never create
  `inits/services/chronology/panel/` for a single leaf. Never create
  `pacts/{subdomain}/{context}.py` while the subdomain has only one context.
  Reverse the speculative scaffold; flatten back when the leaf count drops.
- **Split links by kind first.** Default: one file per kind. When a kind
  crosses ~1000 lines, **promote it to a package** and split into submodules
  (`kind1/part1.py`, `kind1/part2.py`) — same pattern as growing `views.py`
  into `views/`. Do **not** create suffixed siblings (`kind1_a.py`). The
  baseline is **halve, don't shard, and arrange parts to avoid circular
  imports**; the right grouping is adapter-specific (e.g. `db/django` models
  often split by FK dependency hierarchy or aggregate, repositories by
  aggregate group; an external-API adapter may not need to split at all). The
  `links/{port}/{adapter}/__init__.py` facade keeps the public import path
  stable across the promotion. Django technicality for `db/django`:
  `models/__init__.py` must re-export model classes so app-loading finds them;
  `repositories/__init__.py` can stay empty since the facade lives at the
  parent.

When in doubt, keep it flat. The ~12 rule and the ~1000-line rule are escape
hatches, not invitations.

## Patterns

1. **Views return DTOs, never models.** Templates receive Pydantic DTOs.
2. **Views call services, not repos.** `request.services.<name>.method(...)` is
   the data path out of a view — never import a repo or model in a view, never
   reach a repository directly. Services are exposed as a flat namespace
   (`request.services.<service_name>`) wired in `inits/services.py`. The
   `request.di.uow.*` surface is legacy and being retired: new code never uses
   it and must not extend it.
3. **Repository identity map.** Check cache → query ORM → cache → return DTO.
4. **Services take specific repo protocols + a `TransactionProtocol` via
   constructor** — not the full UoW, not imports of concrete repos. ISP at the
   service boundary: declare the two-or-three protocols actually used.
5. **Mills Django-free.** Only protocols and DTOs from pacts.
6. **Writes use TypedDicts.** DTOs for reads, TypedDicts for writes.
7. **Request typed as `RootRequestProtocol`** from pacts.
8. **Multi-repo writes use `transaction.atomic()` from `TransactionProtocol`** —
   not `uow.atomic()` in services. Views never start transactions; that is a
   service concern.
9. New repo methods need matching Protocol in pacts.
10. New DTOs need `model_config = ConfigDict(from_attributes=True)`.
11. New repositories exposed as `@cached_property` on `inits/repositories.py`
    (flat). New services exposed as `@cached_property` on `inits/services.py`
    (flat). See **Growing rules** for when to bucket.
12. **Protocol implementations declare the protocol as a base class** — so the
    intent is explicit and the type checker verifies conformance. Exception:
    very generic structural protocols (`TransactionProtocol`, callbacks) with
    multiple unrelated duck-typed implementations.

## Dependency direction

**Cross-subdomain access is fine.** Repos cross subdomains freely — data access
is not behavior. A view in one subdomain reading another subdomain's users is
normal, not a boundary violation. The smell to watch is duplicated *behavior*
across subdomains; the fix is an aggregate invariant (enforced at
construction/transition) or a shared lower-level mill function, not a rule
against cross-subdomain repo reads.

**Service-to-service calls are fine** when reusing real orchestration. The
genuine smells are narrower: layering inversion (a low-level unit depending on a
high-level orchestrator), cycles, and anemic delegation (one service calling
another for a single trivial read it could do via a repo).

## Testing

The layer under test dictates the test type — not convenience, not what is
easiest for coverage:

- Pure-logic core (`mills`) → **unit** tests. No IO; mock at the highest level
  and assert every mock call.
- IO-bearing boundary layers (`links`, `gates`, adapters, templates) →
  **integration** tests against real infrastructure. Mock at the lowest level or
  not at all; assert side effects.

An uncovered line is covered by the test type that owns its layer — never raise
`links`/`gates` coverage with a mock-everything unit test of IO-bearing code
(views, repositories, importers). Exception: a pure, IO-free helper (no DB,
HTTP, request/response, template render, or framework objects) may be
unit-tested wherever it lives.

## Drift red flags

- Layer kept as single file instead of package
- Nested folders holding one or two small files (see **Growing rules** — folder
  needs ≥2 leaves)
- Folder created for a single file (e.g.
  `inits/services/chronology/panel/personal_data_fields.py` with no sibling) —
  flatten until the bucket is justified
- Port axis inside `mills/` or `specs/` (e.g. `mills/web/...`)
- `specs` imported from `links`, `gates`, or `inits` — specs are only for mills
- `pacts/dtos.py`, `pacts/protocols.py`, or `pacts/repos/` instead of
  `pacts/{subdomain}.py`
- `common/` or `shared/` folder in any layer
- `pacts/` sliced by entity while `mills/` sliced by context (or vice versa) —
  axes must match
- Model and repository in the same `links` file (collapses the
  internal-vs-public boundary)
- ORM model imported from outside `links/` (use the repo protocol from `pacts`
  instead)
- `links/{port}/{adapter}/__init__.py` re-exporting models, or omitting a public
  repo class (the facade is the public surface)
- Suffix-sibling links files (`repositories_chronology.py`, `models_crowd.py`) —
  promote to a `{kind}/` package with submodules instead
- `mills/{entity}.py` holding context-specific write logic (entity-level mills
  exist only for entity-level invariants)
- New view that types `request.di.uow.*` — that surface is legacy; new code must
  call a service via `request.services.*`. If no service exists, create one in
  mills + protocol in pacts + leaf in `inits/services.py` before writing the
  view
