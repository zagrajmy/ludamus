---
name: glimpse
description: >-
  GLIMPSE architecture rules for Python projects. Load before creating,
  moving, or reviewing anything under pacts, specs, mills, links, gates, or
  inits: services, repositories, DTOs, protocols, entry points, DI wiring.
  Covers layer import rules, file layout and slicing (noun, verb, page, port,
  adapter, kind), the __init__.py re-export policy, growth thresholds,
  required patterns, and drift red flags. Also use when deciding where new
  code goes or which test type a layer needs.
---

<!-- Generated from SKILL.src.md — edit that, then run: mise run skill -->

# GLIMPSE Architecture Reference

This file is the compressed form of the full reference at
<https://glimpse.fancysnake.dev/>, which is authoritative where the two
disagree and carries the worked examples and the reasoning behind each rule.

## Layers

```text
pacts   Protocols, DTOs, errors, enums, TypedDicts. Depends on nothing.
specs   Business invariants (pure constants, no IO). Only for mills; see below.
mills   Business logic, services. Depends on pacts + specs. No side-effect imports.
links   Repositories, external clients. pacts + ORM / driver / SDK.
gates   Entry points: request handlers, forms, routing, CLI commands. pacts only.
inits   DI container, middleware. The only layer where gates, mills, links meet.
edges   Settings, wsgi, manage.py. Outside GLIMPSE; empty on a CLI, never absent.
```

All seven exist from the first commit — `edges/` as an empty package where the
project has nothing for it. The import contracts are taken as a set on day one,
and a contract can only name a module that exists.

Import rules enforced by `importlinter` (`pyproject.toml` →
`[tool.importlinter]`). No exceptions without explicit approval.

**What is fixed, and what is guidance.** Absolute: which layer code belongs to,
and which layer may import which. Everything below — slicing axes, thresholds,
file names, patterns — is recorded practice. Follow it by default; treat an
arrangement it does not describe as legitimate when it follows a real need and
breaks no import rule. **Absence of a rule is not a violation**, so do not
flag code for failing to match a shape this reference never required.

**Composition is per-port.** `inits` composes the object graph everywhere; how
it reaches gates differs. Web: the framework dispatches to gates, so `inits`
never imports them — middleware builds `Services()` per request and attaches
it to the request (the framework's thread-safe seam). CLI: nothing dispatches,
so `inits` imports the gate classes, injects mills into their constructors,
and is named by dotted string in `pyproject.toml`
(`[project.scripts]` → `myproject.inits.cli:run`).

**edges is two-way isolated.** Nothing imports `edges`; `edges` imports
nothing first-party — it names project code only by dotted string
(`DJANGO_SETTINGS_MODULE`, `MIDDLEWARE`, `ROOT_URLCONF`). The root middleware
imports services, so it lives in `inits`, not `edges`.

**specs or pacts — what it is, not where it is used.** A constant more than one
layer must enforce is a fact about the shape of the data (a max length lives in
the column, the form, and the rule) — that is a contract, so it goes to `pacts`
beside the DTO it constrains. A constant only the rule can observe (seat limit,
grace period) is a business invariant and goes to `specs`, which mills alone may
import: a threshold reaching `links` ends up encoded in the schema. Tell: change
a `specs` value and only `mills` changes; change a `pacts` value and every
enforcer changes together.

**Configuration enters at `inits`.** `inits` reads the environment and passes
each value to the leaf that needs it; `mills` never reads settings at all. On a
framework with a settings singleton, `links` and `gates` read it through the
framework's accessor (`django.conf.settings`) — an import of the framework, not
of `edges`. Without such a framework there is no settings layer at all, and
`edges/` stays empty. A leaf may still probe its own environment when the
probe is injectable for tests; what the environment *decides*, `inits`
decides. User
input read at runtime — a config file, a command flag — is not configuration:
it comes in through a port, shaped in `pacts`, validated in a mill.

**"Framework-free" means no side effects, not package names.** Forbidden in
`mills`: imports that do IO, touch global state, or own control flow (ORM,
HTTP machinery, settings access). Pure computation is fine wherever it comes
from — `django.utils.text.slugify` qualifies. Enforcement level (ban package /
review-guarded / ban effectful subtrees) is a per-project choice.

The rule guards against destructive operations and output the program depends
on, not everything ambient: the clock, a random draw, a UUID, a log line are
all fine in a mill, and all mockable. Logging reads better at the edge anyway
(mills raise, gates catch and log) — a preference, not a rule. If a generated
value is *input* to what the service does rather than something it produces on
the way, take it as an argument; when the making is somebody else's job, that
is a link, and a link earns its place even as a one-line wrapper because it
names an external capability.

**No DDD tactical patterns.** GLIMPSE has no aggregates or value objects —
data moves as DTOs and write TypedDicts; invariants live in service code. The
slicing axes are GLIMPSE's own (see **Slicing vocabulary**).

## File layout

**`pacts`, `specs`, `mills`, `inits` start as single modules; `links` and
`gates` are packages from day one.** The first three are sliced by noun, and on
day one you have one `mills.py` — don't plan further ahead. `inits` stays thin
whatever the project does, so split it however is convenient. `links` and
`gates` take the port axis immediately: the port is knowable before a line is
written — you know you are building a CLI, you know you are talking to a
database — and skipping it means renaming every import the day a second adapter
appears.

```text
# Day one — axis-free layers stay flat
pacts.py
specs.py
mills.py
inits.py
links/{port}/{adapter}.py                   # e.g. links/db/sqlite.py
gates/{port}/{adapter}.py                   # e.g. gates/cli/argparse.py
edges/__init__.py                           # empty until a framework fills it

# Grown
pacts/{noun}.py                             # or pacts/{noun}/{verb}.py
pacts/{port}.py                             # port machinery (e.g. pacts/db.py)
pacts/services.py                           # ServicesProtocol + service protocols
specs/{noun}.py
mills/{noun}.py                             # or mills/{noun}/{verb}.py
inits/repositories.py                       # a module per registry, plus one that binds
inits/services.py                           # (+ middleware.py on web, cli.py on a CLI)
links/{port}/{adapter}/{kind}.py            # while small (models.py, repositories.py)
links/{port}/{adapter}/{kind}/{module}.py   # when {kind} crosses threshold
links/{port}/{adapter}/__init__.py          # facade — re-exports the public surface
gates/{port}/{adapter}/{page}.py            # or .../{page_group}/{page}.py,
gates/{port}/{adapter}/{page}/{subpage}.py  #    or .../{page}/{subpage}.py
```

Thresholds for every promotion above: **Growing rules**.

**`__init__.py` re-export policy.** Default: keep `__init__.py` empty and import
each symbol from the module that defines it (`from pkg.foo.bar import Bar`, not
`from pkg.foo import Bar`). A facade `__init__.py` that re-exports a public
surface is allowed only for: a framework or public-API package whose inner
layout is implementation detail (the `links` adapter facade), relief from
line-length pressure, or a pre-existing legacy facade. It is not the default.

## Slicing vocabulary

**Port**
: A delivery mechanism, named after the domain concept rather than the
  technology.
: Examples: `cli`, `web`, `db`, `payment_api`, `email`
: The first axis for `links` and `gates`, known before any code exists.

**Adapter**
: The specific technology implementing a port.
: Examples: `postgres`, `sqlite`, `argparse`, `stripe`, `sendgrid`
: One port can have multiple adapters — usually **coexisting**, not
  interchangeable. `payment_api/stripe` and `payment_api/paypal` are both wired
  and both live; which one handles a given payment is a business decision made
  in a mill, through the protocols it holds. Genuine substitution
  (`db/postgres` vs `db/sqlite`) is the rarer case: one adapter wired per
  deployment, chosen in `inits`.
: One technology can serve multiple ports. A full-stack framework shipping both
  an ORM and a request layer appears as `db/{framework}` and `web/{framework}` —
  two separate adapters that share nothing but a name.

**Kind**
: The type of thing a `links` module holds, below the adapter.
: Examples: `models` and `repositories` for a `db` adapter; `transport`,
  `types`, `signer` for an API client.
: Kinds are per-adapter. The `db` shape is not a universal template.

**Noun**
: A fat data cow — the model cluster everything else hangs off.
: Examples: `invoices`, `customers`, `proposals`, `users`
: The primary slicing axis for `pacts`, `mills`, and `specs`.
: Which nouns exist depends on what the system is *for*, not on the words in
  the domain. An invoice tracker slices by `invoices`; a subscription service
  slices by `billing`, and an invoice is a detail inside it.
: Plurality is not prescribed; it follows the noun. `events` are many, a
  `panel` is one.
: Nouns are GLIMPSE's own axis, not a DDD import. If another axis fits a
  project better, slice by that instead; the layer rules don't change.

**Verb**
: An activity cut inside a noun.
: Examples: `issue`, `refund`, `enroll`, `schedule`
: A verb module holds the records and logic of actions, not first-class data.
  Verbs nest inside nouns: `invoices` might cut into `issue` and `refund`.
: No catch-all verbs. `manage`, `organize`, and `misc` name no activity — if
  you cannot name a real one, the file is not too big yet.

**Page**
: What the user touches — the slicing axis for `gates`, below port and adapter.
: Gates take whatever grouping the interface already has: a command or command
  group for a CLI, a page group and page — or a page and its subpages — for the
  web, a view for a TUI, a tool for MCP.
: Gates mirror the shape of the interface; mills mirror the domain. The two
  need not line up, and forcing them to is how a sitemap ends up in `mills`.

**Entity**
: A persistence-level concept: the unit that a DTO and a repository wrap.
: Narrower than a noun — one noun spans many entities.
: Conceptual, **not a file-layout axis**. `links` slices by kind, so one
  `models.py` holds many entities' models. There is no
  `links/db/{adapter}/{entity}.py`.

A noun contains verb cuts. A verb cut depends on entities.

## Slicing rules

**pacts, mills, specs — by noun, then verb. links — port / adapter / kind.
gates — port / adapter / page. inits — however is convenient.**

Each pacts module holds all boundary contracts for that noun or verb cut:
DTOs, write TypedDicts, repository protocols, errors. Split by domain concern,
not by technical kind — no `pacts/dtos.py`, `pacts/protocols.py`, or
`pacts/repos/` directories, and never a `pacts/core.py` or `common` bucket. A
contract two nouns share gets no bucket either: it stays in the noun that
needed it first, and earns its own module named after the thing it is
(`pacts/money.py`) once the sharing makes the case. The ban is on the name, not
on the extraction.

**pacts placement algorithm** — pacts mirrors the whole system; place each
contract by three questions, in order: (1) tied to a noun? →
`pacts/{noun}.py` (DTOs, write dicts, domain errors, repo protocols);
(2) tied to a port? → `pacts/{port}.py` (e.g. `pacts/db.py` for
`TransactionProtocol` — test: would it survive a total change of business
domain?); (3) about the wiring? → `pacts/services.py` for `ServicesProtocol`
**and the service protocols it names** — that module mirrors `inits/services.py`,
and a service protocol describes a registry leaf, not the noun its methods
mention.

**Protocols exist where a boundary needs them, not by policy.** Repository
protocols: essential — mills depend on them. Service protocols: optional —
needed for every service on a typed services namespace (web always; a CLI when
`inits` hands the gate the whole registry rather than individual mills) and
recommended for service-to-service dependencies. Gate classes: no protocols —
nothing outside inits refers to them.

**Errors are coarse and shared** (`NotFoundError`, not `ProposalNotFound`);
the gate catching one decides what it means for that screen, at the call-site
— no central error-to-status mapping. Adapter code translates store exceptions
into pacts errors (`IntegrityError` → `DatabaseConstraintError`), so no ORM
exception reaches a mill.

**Boundary vs core — where does it go?** Decide by what the code does. If it
*crosses a boundary* (data shapes moving between layers) it is a contract →
`pacts` (DTOs, protocols). If it *enforces business rules* (service logic,
invariants) it is core → `mills`. DTOs stay in `pacts` even though
they feel like domain objects: repo protocols in `pacts` return them, so moving
them to `mills` would make `pacts → mills → pacts` circular. A DTO is a data
contract for a port, not a domain object.

**Repo methods follow the needs.** Parameters express variation within a use
case; a different scope is a different method. Filtering an event's meetings
by facilitator or topic: parameters. Switching events or including
never-accepted meetings: a second use case → a second method. No generic
query objects through the protocol.

**A `links` adapter's kinds are its own** — a `db` adapter is not the universal
template. For `db`, the kinds are typically `models` (internal) and
`repositories` (public, exposed through the facade and consumed via the
protocols in `pacts`); a `payment_api/stripe` adapter may stay a single file, or
split into transport / types / signer with no internal-vs-public distinction.
The public face of any `links` adapter is whatever its facade re-exports —
internal modules stay internal, so external code does `from
myproject.links.db.postgres import SessionRepository` and never reaches
`models`.

`pacts` and `mills` share the noun/verb axis, but nothing requires them to
promote in lockstep — `mills/` may be a package while `pacts.py` is still one
file. Nothing enforces it and nothing depends on it.

## Growing rules

**Default: start as small as possible. Split only when size or friction makes
the case for itself.** Premature splitting creates churn, bloats the import
graph, and makes the layout look complete before the requirements actually
demand it.

Concrete thresholds — none is a hard line, all are "watch for this":

- **A layer becomes a package when it earns it.** Promote `mills.py` → `mills/`
  on any one of: it crosses ~1000 lines, two unrelated concerns in it cause
  merge friction, or a second noun genuinely exists. Not before. `inits` is a
  convenience call either way — it stays thin whatever it holds.
- **~1000 lines per file** — split a file when it crosses this and the two
  halves are unrelated enough that they cause merge friction. A 1500-line file
  holding one tightly coupled service is fine; a 600-line file holding three
  independent services is not.
- **~12 public symbols per namespace level** — applies to repository
  registries, the services tree, pacts noun modules, and the inits namespaces.
  At 13+ leaves, introduce a sub-bucket grouped by noun or verb. With ≤12,
  stay flat.
- **Folder must contain at least 2 files before it exists.** Never create
  `inits/services/invoices/issuing/` for a single leaf. Never create
  `pacts/{noun}/{verb}.py` while the noun has only one cut.
  Reverse the speculative scaffold; flatten back when the leaf count drops.
- **Split links by kind first.** Default: one file per kind. When a kind
  crosses ~1000 lines, **promote it to a package** and split into submodules
  (`kind1/part1.py`, `kind1/part2.py`) — same pattern as growing `views.py`
  into `views/`. Do **not** create suffixed siblings (`kind1_a.py`). The
  baseline is **halve, don't shard, and arrange parts to avoid circular
  imports**; the right grouping is adapter-specific (e.g. `db` models often
  split by foreign-key dependency hierarchy — the entities that change
  together — repositories along the same lines; an external-API adapter may
  not need to split at all). The
  `links/{port}/{adapter}/__init__.py` facade keeps the public import path
  stable across the promotion. Framework technicality: if the ORM discovers
  model classes by importing the package (Django does), `models/__init__.py`
  must re-export them; `repositories/__init__.py` can stay empty since the
  facade lives at the parent.

When in doubt, keep it flat. The ~12 rule and the ~1000-line rule are escape
hatches, not invitations.

## Patterns

1. **Entry points return DTOs, never models.** Templates, serializers, and CLI
   output receive DTOs from pacts. ORM instances never leave `links`.
2. **Entry points call services, not repos.** `request.services.<name>.method(...)`
   is the data path out of a view — `pacts` is the only project import a gate
   has, so never a repo, a model, or a service class, and never a repository
   reached directly. Services are exposed as a flat namespace
   wired in `inits/services.py`; CLI gates receive theirs at construction.
3. **Services take specific repo protocols + a `TransactionProtocol` via
   constructor** — not imports of concrete repos, not dependencies passed as
   method arguments. With an ambient ORM (Django), never a whole Unit of Work;
   with a session-based ORM (SQLAlchemy) the session already is one, and
   injecting it is idiomatic. ISP at the service boundary: declare the
   two-or-three protocols actually used.
4. **Mills have no side-effect imports.** Only protocols and DTOs from pacts,
   constants from specs, pure helpers from anywhere (see **Layers**).
5. **Writes use TypedDicts.** DTOs for reads, TypedDicts for writes — gates →
   mills as input, mills → links as what repo write methods accept
   (`create(data: CreateProposalDict) -> ProposalDTO`; a `CreateXDict` has no
   `id` — the store assigns it). The split is the `id`: a nullable one on the
   DTO would push a null check into everything that touches it, and a write
   shape is short-lived enough that it never makes the trip a DTO makes.
6. **Web requests typed via a gate-local typing-only subclass** of the
   framework request (`class RootRequest(HttpRequest): services:
   ServicesProtocol` in the web adapter) — never instantiated; middleware
   mutates the real request. Only `ServicesProtocol` comes from pacts. CLI
   gates have no context.
7. **Multi-repo writes use `transaction.atomic()` from `TransactionProtocol`.**
   Entry points never start transactions; that is a service concern. The
   protocol: `atomic()` and `savepoint()`, both returning a context manager;
   `savepoint()` rolls back only its block on constraint violation,
   re-raising as a pacts error with the outer transaction usable. The
   implementation is inits binding glue when it wraps an ambient ORM with no
   store behind it, and a links adapter when it holds a connection.
8. New repo methods need matching Protocol in pacts.
9. **DTOs must be constructible from what the adapter loaded.** Pydantic is not
   required — a dataclass, `NamedTuple`, or attrs class is a DTO too (write
   shapes are already `TypedDict`, so `pacts` can be pure stdlib); pick one and
   use it throughout. With Pydantic, attribute rows (an ORM instance) need
   `model_config = ConfigDict(from_attributes=True)`; mapping rows
   (`sqlite3.Row`, a dict cursor) validate from `dict(row)` with no config;
   without it, construction is a plain call. A row that does not match the DTO
   is mapped in the repository, not by a method on the DTO.
10. New repositories exposed as `@cached_property` on `inits/repositories.py`
    (flat). New services exposed as `@cached_property` on `inits/services.py`
    (flat, zero-arg `Services()` builds its own dependencies — no DI inside
    the composition root). Lifetimes: `@cached_property` = per container
    (per request); `@functools.lru_cache` on a module-level inits factory =
    per process (pooled clients, connections). Closing follows the owner: a
    process-lifetime connection is wound down in inits (often nothing to
    write — exit does it); one opened mid-flight is closed by a context manager
    the link exposes, like `TransactionProtocol`. See **Growing rules** for
    when to bucket.
11. **Protocol implementations declare the protocol as a base class** — where
    a protocol exists — so the intent is explicit and a type checker verifies
    conformance. This assumes one runs: an explicit `Protocol` subclass
    inherits the stub bodies, so an unimplemented method returns `None` rather
    than failing. Exception: very generic structural protocols
    (`TransactionProtocol`, callbacks) with multiple unrelated duck-typed
    implementations.
12. **Gates validate format, mills validate meaning.** A gate checks input
    parses (an email, an int); a mill checks it makes sense ("email or
    username required", seat limits from specs). Parse vs semantics, not
    single-field vs cross-field. Permissions: trivial checks
    (`is_authenticated`) in gates; rule-bearing permission systems in mills.
13. **Django apps are markers, not structure.** An `AppConfig` sits at the
    lowest directory Django must discover (models, commands, templatetags),
    with a custom `label` (names all end in `.django` — default labels
    collide). Migrations live in `links/db/{framework}/migrations/`; admin
    (model-coupled by design) at `links/db/django/admin.py`; plain `Form`s
    only, never `ModelForm`. Framework-owned surfaces (`request.user`,
    `django_login`) are named exemptions — contain them in gates; mills see
    ids and DTOs.

## Dependency direction

**Cross-noun access is fine.** Repos cross nouns freely — data access is not
behavior. An entry point on one noun's turf reading another noun's data is
normal, not a boundary violation. The smell to watch is duplicated *behavior*
across nouns; the fix is a shared lower-level mill function that both call,
not a rule against cross-noun repo reads.

**Service-to-service calls are fine** when reusing real orchestration. The
genuine smells are narrower: layering inversion (a low-level unit depending on a
high-level orchestrator), cycles, and anemic delegation (one service calling
another for a single trivial read it could do via a repo).

## Testing

The layer under test dictates the test type — not convenience, not what is
easiest for coverage:

- Pure-logic core (`mills`) → **unit** tests. No IO; the service gets
  `MagicMock`s for the repo protocols (and for data when only one field
  matters); assert how the mocks were called. `MagicMock` covers
  `TransactionProtocol` — it speaks the context-manager protocol.
- IO-bearing boundary layers (`links`, `gates`, adapters, templates) →
  **integration** tests against real infrastructure. Mock at the lowest level or
  not at all; assert side effects. A gate test is a full-request test via the
  framework's test client, asserting **all** fields of the response (context
  data, redirect URL, status), with strict templates that fail on unknown
  variables.

Tests live in a repo-root `tests/` split by type — `tests/unit/` (mills, plus
pure helpers from any layer; organised by convenience, not mirroring the
code) and `tests/integration/` (gates by port + page, links by port +
adapter).

An uncovered line is covered by the test type that owns its layer — never raise
`links`/`gates` coverage with a mock-everything unit test of IO-bearing code
(views, commands, repositories, importers). Exception: a pure, IO-free helper
(no DB, HTTP, request/response, template render, or framework objects) may be
unit-tested wherever it lives.

## Drift red flags

### Layout and slicing

**`links.py` or `gates.py` as a single file**
: Both need the `{port}/{adapter}` axis from day one. The port is knowable
  before any code is written; deferring it costs an import rewrite the day a
  second adapter appears.

**A layer promoted to a package before it earned it**
: `pacts/`, `specs/`, or `mills/` as a directory while there is one noun, well
  under ~1000 lines, and no merge friction. The tree is anticipating nouns you
  have not discovered.

**Nested folders holding one or two small files**
: `pacts/invoices/issue/create.py` when `pacts/invoices/issue.py` would do, or
  `inits/services/invoices/issuing.py` with no sibling. A folder needs at least
  two leaves to exist.

**Port axis inside mills or specs**
: `mills/web/proposals.py` or `specs/api/...`. Mills and specs have no
  delivery-mechanism axis. If you see a port word inside these layers, the code
  belongs elsewhere.

**A catch-all verb module**
: `manage.py`, `organize.py`, `misc.py` inside a noun. A verb cut must name a
  real activity.

**A noun axis inside gates**
: `gates/web/django/invoices.py` when the interface has no such page. Gates
  mirror the interface; mills mirror the domain. The two trees are not expected
  to match.

**`common`, `shared`, `utils`, or `entities` as a module or folder name**
: Magnets for unrelated code. Each says where a file sits, not what it holds,
  so anything can be filed there and nothing can ever be found. Shared types go
  to `pacts`, under the noun that needed them first; everything else takes a
  name from the axis it belongs to. The exception is a real concept that
  happens to carry the word — a `DOMEntity` in a browser-port adapter earns
  `entities.py`; a bag of dataclasses does not.

### pacts

**pacts split by technical kind instead of noun**
: `pacts/dtos.py`, `pacts/protocols.py`, `pacts/repos/`. These group by what
  the type *is*, not by what domain concern it belongs to. This forces
  unrelated nouns to share files and makes the package harder to navigate.

**`pacts/core.py`, `pacts/common.py`, or similar**
: A `common/` bucket wearing a nicer name. Every contract has a principled home
  under the noun / port / wiring axes.

**A DTO that cannot be built from a store row or ORM instance**
: Repositories cannot return it. Whatever the project uses for DTOs — Pydantic
  is not required — construction has to work from the row the adapter loaded.
  A row that does not match the DTO is mapped in the repository, not by a
  method on the DTO.

**A protocol implementation that does not name the protocol as a base class**
: The conformance check is left to a structural match that can silently drift.
  The exception is very generic structural protocols — `TransactionProtocol`,
  callbacks — with multiple unrelated duck-typed implementations.

### specs

**specs imported from links, gates, or inits**
: `specs` are business invariants, and business rules are enforced in `mills`
  alone. A constant needed elsewhere is either a contract (`pacts` — a max
  length or an allowed range is a fact about the shape of the data, and belongs
  beside the contract it constrains) or configuration, which enters at `inits`
  or comes from the framework's settings accessor where there is one.

**specs reading from `os.environ` or `settings`, or performing IO**
: It is a constants layer. Environment-dependent values enter at `inits`.

### mills

**mills importing anything with side effects**
: An ORM, HTTP machinery, a CLI parser, settings access — absolute violation.
  Pure computation is fine wherever it comes from. So is the ambient stuff the
  rule was never about: the clock, a random draw, a UUID, a log line.

**A service taking a whole Unit of Work instead of the protocols it uses**
: Applies to ambient-ORM projects. With a session-based ORM the session already
  is a unit of work, and injecting it is idiomatic.

**A page axis inside mills**
: Gates mirror the interface, mills mirror the domain. A sitemap in `mills` is
  the interface leaking inward.

### links

**Model and repository in the same links file**
: This collapses the internal-vs-public boundary. Models are internal to the
  adapter; repositories are its public surface.

**links files named per entity**
: `links/db/postgres/user.py`. `links` slices by kind, not by entity. One
  `models.py` holds many entities' models.

**Suffix-sibling links files**
: `repositories_invoices.py`, `models_users.py`. Promote the kind to a
  `{kind}/` package with submodules instead. Halve, don't shard.

**A links facade that re-exports models, or omits a public repository**
: `links/{port}/{adapter}/__init__.py` *is* the public surface. Whatever it
  exports is public; everything else is internal.

**An ORM model imported from outside links/**
: Use the repository protocol from `pacts` instead.

**A repository imported directly in a gate or a mill**
: Inject it through `inits`.

### gates

**A gate importing project code other than `pacts`**
: An ORM model, a repository class, a service class from `mills` — all the same
  violation. A gate calls services through their protocols. If none exists,
  create one — a mill in `mills`, a protocol in `pacts`, a leaf in
  `inits/services.py` — before writing the gate.

**A gate returning ORM instances to templates or serializers**
: Return DTOs from `pacts`. ORM instances never leave `links`.

**A gate that opens a transaction**
: Atomicity is a service concern.

**Business rules in form validation**
: Gates validate format — an email, an int, a date. Meaning ("email or username
  required", seat limits) belongs in mills, which alone may read `specs`.

**A non-port axis at the top level of gates**
: `gates/mills/...`. The first axis below `gates` is always the port.

### inits

**A gate constructing repository or service instances**
: That is the wiring `inits` owns, and doing it in a gate breaks it.

**mills importing from inits**
: The dependency runs the other way. `inits` knows the concrete classes;
  `mills` sees only protocols.

**inits containing business logic**
: It should only wire, never decide.
