# Effect-TS learnings for Ludamus

What the design of [Effect](https://effect.website) (the TypeScript effect
system) and the practices of its codebase suggest for Ludamus. Effect's core
idea — `Effect<Success, Error, Requirements>` — makes three things explicit
in every function signature: what it returns, how it can fail, and what it
needs. GLIMPSE already encodes two of the three; the gaps cluster around the
error channel and a few dependencies that are still ambient.

## Where GLIMPSE is already Effect-shaped

Worth stating so we protect these properties instead of rediscovering them:

- **The `Requirements` channel.** Services taking specific repo protocols +
  `TransactionProtocol` via constructor (`mills/`), never the full UoW, is
  exactly Effect's per-service `Context.Tag` requirements. The
  `inits/services.py` registry with `cached_property` mirrors Layer
  memoization; `request.services.<name>` mirrors flat service access.
- **Schema at the boundary.** Pydantic DTOs validated on the way in and
  returned to templates ≈ `Schema.decode` at the edge, parse-don't-validate.
- **Interface/implementation package split.** `pacts` (protocols) vs `links`
  (drivers) is Effect's `@effect/platform` vs `platform-node` split.
- **Resource safety.** `TransactionProtocol.atomic()` / `savepoint()` as
  context managers owned by services ≈ `Scope` / `acquireRelease` — the
  boundary is held by the layer that understands the invariant.
- **Enforced layering.** Effect enforces its architecture with types; we
  enforce ours with importlinter. Same property, different mechanism.
- **Migration discipline.** Effect ships codemods and tracks deprecations;
  our tingle debt metrics + strangler-fig recipe play the same role.

## Learnings to apply

Ordered by value-for-effort.

### 1. Expected failure vs defect (`fail` vs `die`)

Effect's sharpest idea: an error a caller is *expected to handle* lives in
the signature; a bug is a defect that crashes loudly. We are inconsistent:

- **Already right:** `WaitlistPromotionServiceProtocol.claim_offer` returns
  `ClaimResult` — the outcome is data, callers must branch. This is the
  house pattern to spread.
- **Halfway:** `AnonymousEnrollmentError` carries a typed
  `AnonymousEnrollmentErrorCode` — good — but nothing ties the code set to
  the protocol, and handling is spot-checked (see learning 2).
- **Wrong side of the line:** panel timetable views catch `KeyError` and
  `ValueError` escaping services. Those are defects being handled as
  expected errors — a genuine bug in a service gets converted into a polite
  redirect and disappears. Gates should parse request input *before* calling
  the service (a `ValueError` from parsing belongs to the gate); anything
  non-domain escaping a service should reach the 500 handler and Sentry.

Rule to adopt: a service method's expected failures are either a result DTO
(discriminated union on a `StrEnum` status) or named, payload-carrying
exception classes defined in the same `pacts` module as the protocol.
`except ValueError` / `except KeyError` around a service call is a smell —
it means either the gate skipped parsing or a defect is being swallowed.

### 2. Exhaustive error handling (`catchTag` → `match` + `assert_never`)

Effect's `catchTag` fails compilation when a handled error is removed or a
new one appears. Our equivalent is `match` on the code enum with
`typing.assert_never` in the default arm — currently unused in the codebase.
Concrete gap: `_ERROR_MESSAGES` in `gates/web/django/chronology/anonymous.py`
is a dict indexed by `AnonymousEnrollmentErrorCode`; adding a code compiles,
type-checks, and then `KeyError`s at runtime in the error path — the exact
place we least test. Any per-code branching (dict lookups included) should
be a `match` with `assert_never`, so mypy flags the missing arm the moment a
code is added.

### 3. Clock as a dependency (`Clock` / `TestClock`)

Effect puts time behind a service, so tests control it without patching.
`mills/enrollment.py` calls `datetime.now(UTC)` directly in ~10 places
(enrollment windows, offer expiry — logic where *time is the input*), and
tests reach for freezegun, which monkeypatches globally. Add a
`ClockProtocol` next to `TransactionProtocol` in `pacts/services.py`, a
trivial real implementation wired in `inits`, and inject it into
time-sensitive services. Unit tests then pass a fixed clock; time becomes a
visible constructor dependency instead of an ambient one. Freezegun remains
fine for integration tests of legacy paths.

### 4. Branded ids (`Schema.brand` → `NewType`)

In Effect, `UserId` and `EventId` are distinct types even though both are
strings. Our signatures pass bare `int` pks everywhere (`event_pk: int`,
`session_id: int`), so swapping two ids type-checks fine. Python's
`NewType("EventId", int)` costs nothing at runtime and makes mypy catch the
swap. This directly reinforces the panel object-scope authz effort
(refactor #5): a repo method typed `read(pk: SessionId, event: EventId)`
can't silently receive arguments in the wrong order from a view. Adopt
incrementally: define the `NewType`s in `pacts`, use them in new/migrated
service and repo protocols; no big-bang rename.

### 5. Retry policy as a shared value (`Schedule`)

Effect composes retry policies as data (`exponential + jitter + cap`) and
attaches them per call. `links/ticket_api.py` and `links/google_docs.py` do
single-shot requests — one transient network blip fails the user-facing
flow. Add one small helper in `links` (a function taking attempts/base
delay/cap, wrapping a callable), declare the policy per client at
construction. Not a framework — ~20 lines, used by the two or three HTTP
clients we have.

### 6. Observability at the wiring layer (`withSpan`)

Effect instruments effect boundaries in the runtime, so user code stays
clean. Most `mills` modules contain zero `logger` calls, and the DoD's "new
path logs meaningful events" relies on per-PR discipline. The Effect move:
instrument once where services are constructed — a thin proxy applied in
`inits/services.py` that logs service name, method, duration, and
outcome/exception for every call. Every current and future service gets
boundary logs for free; hand-written logs inside mills remain for the
genuinely meaningful domain events. (Same hook later becomes the OTel span
wrapper if we adopt tracing.)

### 7. From the Effect repo's practices

- **Compiled doc examples.** Effect type-checks every JSDoc example, so docs
  can't rot. Our `docs/agents/*.md` snippets (repository/service examples)
  have no such check. Cheap variant: prefer snippets that name real modules
  and classes over invented ones, so grep during refactors finds them; the
  full variant (executing doc fences in a test) is likely not worth it yet.
- **Conformance is declared, not assumed.** Effect's dtslint type tests ≈
  our rule that implementations list their `Protocol` as a base class.
  Already policy; keep it.

## What not to import

- **Monadic composition / generators.** `Effect.gen`, `pipe`, and
  Result-wrapping every call are idiomatic where the type system carries
  them. In Python they fight the language; exceptions + context managers are
  the right substrate. Use result unions only where callers genuinely branch
  on outcomes (learning 1), not as a universal wrapper.
- **Fibers / structured concurrency.** Sync Django + DBOS scheduler covers
  our concurrency needs; no place for an interruption model.
- **An Effect-for-Python library.** The value is the discipline, not a
  dependency.

## Suggested sequencing

1. Learning 2 (`match` + `assert_never` on error codes) — small, standalone.
2. Learning 3 (`ClockProtocol`) — small, pays off in enrollment tests.
3. Learning 5 (retry helper in `links`) — small, standalone.
4. Learning 4 (`NewType` ids) — adopt inside the ongoing authz and
   services-migration work rather than as its own pass.
5. Learning 1 (expected-vs-defect audit) — fold into the per-view
   services-migration recipe: when a view migrates, its error contract gets
   the result-DTO-or-named-exception treatment.
6. Learning 6 (service boundary logging proxy) — one PR in `inits`, best
   after a couple of services have migrated so the proxy sees real traffic.
