# GLIMPSE → Hexagonal: Evolutionary Refactor

## Direction

GLIMPSE already has all the structural pieces for hexagonal. The evolution is
two independent changes that can be applied per bounded context incrementally,
with the first landing as a strangler fig so no view sees both shapes at once.

---

## Change 1: Services on a parallel DI namespace

### Services current state

```text
gates → request.di.uow.{repo}.read(id)   # view reaches into repository
gates → mills.{context}.some_service()   # direct import from mills
```

Views know about UoW, know which repos exist, and import concrete mill
functions/classes directly. UoW is two things wearing one hat: a transaction
boundary and a 40+-property repo bag. Every consumer that wants to call
`atomic()` ends up seeing every repo.

### Services target state

```text
gates  → request.services.<service_name>.method(...)
mills  → service constructor takes specific repos + a transaction handle
inits  → wires repos into a flat registry, services into a flat namespace
```

Three orthogonal pieces:

1. **TransactionProtocol** — `atomic()` only. Replaces `uow.atomic()` for
   services. Owned by `inits`, mocked trivially in unit tests.
2. **Repository Registry** — flat, lazy `@cached_property` leaves. Internal
   to `inits/repositories.py`; never imported from gates.
3. **Services namespace** — flat, lazy `@cached_property` leaves at
   `inits/services.py`. Each service constructor declares the specific
   repo protocols it touches plus a `TransactionProtocol` if it writes —
   never the whole UoW. ISP at the service boundary.

Naming: the layer remains `mills/`. The runtime accessor is
`request.services` because that's what view authors think they're calling —
"mills" is internal jargon for the layer.

### Why split UoW

A repo is data access. A transaction is a coordination concern. Bundling them
forced every consumer to see every repo. Splitting lets a service declare a
two-line dependency (`fields_repo`, `categories_repo`, `transaction`) instead
of accepting a 40-property surface. Unit tests stop needing
`MagicMock()`-of-UoW; they pass exactly the protocols the service uses.

### Flat first; bucket only on growth

Default to a flat namespace at both `inits/services.py` and
`inits/repositories.py`. A speculative `chronology.panel.<leaf>` bucket
makes the layout look complete before anything justifies it; commits
`cb42ce6e` and `957a1ed9` walked back exactly that mistake (one leaf
inside a `chronology` bucket, then `panel` inside `chronology`, both
flattened).

**Rule of thumb**: a single namespace level holds up to ~12 members; beyond
that, split into sub-buckets grouped by subdomain or bounded context.
Applies to the repo registry, the services tree, and `pacts` subdomain
modules alike. Until the count crosses the threshold, names like
`personal_data_fields` or `proposals` are findable enough on their own.

A folder must contain at least 2 files before it exists. Reverse and
flatten the moment a bucket drops back to a single leaf.

### Cross-subdomain access is fine

Repos cross subdomains freely — data access is not behavior. Enrollment
reading `crowd.users` is normal and not a boundary violation. The smell to
watch is duplicated *behavior* across subdomains; the fix for that is an
aggregate invariant (preferred — enforced at construction/transition) or a
shared lower-level mill function, not a rule against cross-subdomain repo
access.

Service-to-service calls are also fine when reusing real orchestration. The
genuine smells are narrower: layering inversion (low-level depending on
high-level orchestrator), cycles, and anemic delegation (one service calling
another for one trivial read it could do via a repo).

### How (per file)

1. Add the service protocol + needed DTOs to `pacts/{subdomain}.py`. Add
   the property to `ServicesProtocol` in `pacts/services.py`.
2. Implement the service in `mills/{subdomain}.py` — constructor takes
   specific repo protocols and `TransactionProtocol`.
3. Add the leaf as `@cached_property` on `Services` in `inits/services.py`.
   Add any new repo leaves to `inits/repositories.py`.
4. Migrate the view file: replace `request.di.uow.{repo}` calls with
   `request.services.<service_name>.method(...)`.
5. Existing integration tests are the regression guard. New unit tests for
   the service mock specific repo protocols + transaction.

The reference implementation is `personal_data_fields`. The detailed,
scannable how-to lives at
[docs/agents/services-migration.md](../agents/services-migration.md).

### Migration: strangler fig

`request.di` and the existing `RepositoryInjectionMiddleware` stay untouched
during the migration. A new `ServiceInjectionMiddleware` runs in parallel and
attaches `request.services`. View files migrate one at a time; an unmigrated
view keeps using `request.di.uow.*`, a migrated view uses
`request.services.*`. No view sees both shapes simultaneously.

When the last view is migrated:

- delete `RepositoryInjectionMiddleware` and `request.di.uow`
- decide whether non-repo links (`cache`, `ticket_api`, `gravatar_url`) move
  into `request.services` (uniform boundary) or stay on a slimmed `request.di`

Non-repo links stay on `request.di` until a consumer migration needs them
moved. Don't pull them in preemptively.

---

## Change 2: Pacts restructured by subdomain/context

### Pacts current state

`pacts/{entity}.py` — DTO + write TypedDict + protocol + errors together.

This conflates boundary contracts (protocols) with data shapes (DTOs) and
domain errors. The DDD entity grouping made `pacts` behave like a domain model
layer sitting below business logic, which is an inversion.

### Pacts target state

```text
pacts/
  {subdomain}.py                      # flat when subdomain is small
  {subdomain}/{bounded_context}.py    # split when subdomain grows fat
mills/
  {subdomain}.py                      # same axis — mirror pacts
  {subdomain}/{bounded_context}.py
```

Each pacts module holds whatever belongs to that subdomain/context at the
boundary: DTOs, write TypedDicts, repo protocols, service protocols, errors.
Split by domain concern, not by technical kind (no `repos/`, `services/`,
`clients/` directories). Same ~12-members-per-level rule of thumb applies.

### Splitting criterion

- **Crosses a boundary?** → stays in `pacts` (DTOs, protocols)
- **Enforces business rules?** → belongs in `mills` (aggregates, value objects)

DTOs are boundary contracts — they define the shape of data that moves between
layers. They belong at the port boundary, not inside the core. Aggregates carry
invariants and behaviour — they are the core.

### Why DTOs stay in pacts

Repository protocols in `pacts` return DTOs. If DTOs lived in `mills`,
`pacts` would need to import from `mills`, creating a circular dependency
(`mills` depends on `pacts` depends on `mills`). DTOs at the port boundary
avoids this. The conceptual framing: a DTO is a data contract for a port, not
a domain object.

### When to migrate

Per entity, when the entity accumulates enough invariants and behaviour that
a plain DTO is no longer sufficient. Start by adding aggregate classes to
`mills/{context}.py` alongside existing logic; only split the pacts structure
once the distinction is clear in the code.

---

## Symmetry after both changes

```text
pacts/{subdomain}[/{context}]   ↔  mills/{subdomain}[/{context}]
specs/{subdomain}.py               pure invariants, used only by mills
inits/repositories.py              flat ≤12/level, internal only
inits/services.py                  flat ≤12/level, as request.services
links/{port}/{adapter}/{entity}    implements repo protocols from pacts
links/{port}/{adapter}             implements client protocols from pacts
```

`gates` touches only `pacts` protocols and `request.services`. `mills` owns
domain logic and consumes specific repos + a `TransactionProtocol`, never the
full UoW surface. `inits` wires everything. `specs` sits alongside `pacts`
at the bottom and is imported only by `mills` (`pacts` → `specs` → `mills`);
forbidden in `links`, `gates`, `inits`.

---

## What does NOT change

- Import rules enforced by `importlinter` — same contracts
- `links` depends on `pacts` + Django ORM — unchanged
- `edges` outside GLIMPSE — unchanged
- File layout conventions (1000-line trigger, no premature nesting); the
  ~12-members-per-level rule is the new fan-out guide for namespaces and
  pacts modules
- Test strategy: unit tests for mills (now with specific repo mocks instead
  of UoW MagicMocks), integration tests for views
- The `mills/` layer name stays. `request.services` is the gate-facing
  alias; "mills" remains internal jargon
