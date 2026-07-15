# Plan 008: Batch the per-waiter queries in waitlist promotion state

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. Your reviewer maintains
> `plans/README.md`; do not edit it.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 7ffe8ba..HEAD -- \
>   src/ludamus/links/db/django/enrollment.py \
>   src/ludamus/adapters/db/django/models.py \
>   tests/integration/web/chronology/test_waitlist_promotion.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `7ffe8ba`, 2026-07-10

## Why this matters

`ParticipationPromotionRepository.lock_and_read_state` runs inside a
`select_for_update` transaction on every promotion sweep (freed seat,
offer expiry, decline roll-on). Today it issues one agenda-overlap
query per WAITING participation and, per distinct slot owner, one
active-config listing plus two config lookups per active enrollment
config. On a popular session with N waiters that is O(N) queries
executed while the session row is locked — lengthening lock hold time
and slowing every enrollment action contending on that row. Batching
the conflict check into one query and the config lookups into two
makes the query count independent of the number of waiters, with
byte-identical DTO output.

## Current state

- `src/ludamus/links/db/django/enrollment.py:78-156` —
  `lock_and_read_state`: locks the session, lists WAITING
  participations FIFO, and builds `WaitingParticipantDTO`s in a loop.
  Per-owner slot math is already memoized via `slots_by_owner`, but
  the loop body still queries per waiter:

  ```python
  for participation in participations:
      user = participation.user
      sponsor = sponsors.get(user.pk)
      recipient = sponsor if sponsor is not None else user
      if recipient.pk not in slots_by_owner:
          slots_by_owner[recipient.pk] = self._slots_remaining(
              recipient, event, event_dto
          )
      waiting.append(
          WaitingParticipantDTO(
              ...
              has_conflict=Session.objects.has_conflicts(
                  session, UserDTO.model_validate(user)
              ),
              owner_slots_remaining=slots_by_owner[recipient.pk],
              ...
          )
      )
  ```

- `src/ludamus/links/db/django/enrollment.py:158-195` —
  `_slots_remaining(owner, event, event_dto)`: for each config in
  `event.get_active_enrollment_configs()` it runs
  `UserEnrollmentConfig.objects.filter(enrollment_config=config,
  user_email=owner.email).first()` and (when the email has a domain)
  `DomainEnrollmentConfig.objects.filter(enrollment_config=config,
  domain=domain).first()`, summing `allowed_slots` /
  `allowed_slots_per_user` into `allowed` and tracking `has_config`.
  If no config matched it returns `UNLIMITED_SLOTS`; otherwise it
  subtracts used slots computed from `active_companions(owner.slug)`
  and `EnrollmentParticipationRepository.occupying_user_ids(...)`.
- `src/ludamus/adapters/db/django/models.py:812-835` — the conflict
  semantics to reproduce exactly. `SessionManager` extends
  `AliveManager["Session"]`, so `get_queryset()` is alive-only
  (soft-deleted sessions never conflict):

  ```python
  def has_conflicts(self, session: Session, user: UserDTO) -> bool:
      return (
          self.get_queryset()
          .filter(
              event_id=session.event_id,
              session_participations__user_id=user.pk,
              session_participations__status=(
                  SessionParticipationStatus.CONFIRMED
              ),
          )
          .filter(
              Q(
                  agenda_item__start_time__gte=(
                      session.agenda_item.start_time
                  ),
                  agenda_item__start_time__lt=(
                      session.agenda_item.end_time
                  ),
              )
              | Q(
                  agenda_item__end_time__gt=(
                      session.agenda_item.start_time
                  ),
                  agenda_item__end_time__lte=(
                      session.agenda_item.end_time
                  ),
              )
          )
          .exclude(id=session.id)
          .exists()
      )
  ```

  (Excerpt reformatted to fit this file's line width; the boundary
  operators `gte/lt` and `gt/lte` are the load-bearing part.)
- Other `Session.objects.has_conflicts` callers that must keep
  working unchanged: `src/ludamus/adapters/web/django/views.py:1422`,
  `src/ludamus/adapters/web/django/forms.py:375`, and
  `AnonymousEnrollmentRepository.has_conflicts` at
  `src/ludamus/links/db/django/enrollment.py:415-417`.
- `src/ludamus/adapters/db/django/models.py:534-541` and `:561-568` —
  unique constraints `(enrollment_config, user_email)` on
  `UserEnrollmentConfig` and `(enrollment_config, domain)` on
  `DomainEnrollmentConfig`. Because of these, the current
  per-config `.first()` matches at most one row per pair, so a
  batched `__in` query summed per email/domain is exactly
  equivalent.
- `src/ludamus/adapters/db/django/models.py:401-402` —
  `Event.get_active_enrollment_configs` iterates
  `self.enrollment_configs.all()`; each call is a fresh query (no
  cache), which is why per-owner calls multiply today.
- `src/ludamus/links/db/django/companions.py` —
  `sponsors_by_member` (already batched, one query) and
  `active_companions(leader_slug)` (one query per call, still
  per-owner after this plan — see Maintenance notes).
- Exemplar tests: `TestPromotionRepositoryEdges` in
  `tests/integration/web/chronology/test_waitlist_promotion.py`
  calls `ParticipationPromotionRepository().lock_and_read_state(...)`
  inside `with DjangoTransaction().atomic():`. Query-count assertion
  pattern: `tests/integration/links/test_sphere_repository.py:26-28`
  (`django_assert_num_queries`).
- Repo conventions that apply: functions with 3+ parameters take
  keyword-only args with `*,`; no docstrings; NEVER add
  noqa/type-ignore/pylint directives; mypy strict runs in
  `mise run check`; this is `links`/`adapters` code, so new tests
  are integration tests; in tests never use `ANY` for simple values.
- Environment notes: `export MISE_ENV=sandbox` for all mise commands
  in this container, and run `mise install && poetry install` first.
  Prefix test/check runs with `PATH="$(pwd)/.venv/bin:$PATH"`
  because a global pytest shadows the venv. The CI-style gate is
  `mise run check` (there is no `prcheck` task). PostgreSQL-only
  locking tests carry `@pytest.mark.postgres` and run via
  `mise run test:postgres`; they are auto-skipped on SQLite
  (`tests/conftest.py:19-27`). The tests added here need no such
  marker — existing `lock_and_read_state` tests run on SQLite.

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| All Py tests | `mise run test:py` | all pass |
| Unit tests | `mise run test:unit` | all pass |
| CI-style checks | `mise run check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/adapters/db/django/models.py` (only `SessionManager`)
- `src/ludamus/links/db/django/enrollment.py`
- `tests/integration/web/chronology/test_waitlist_promotion.py`

**Out of scope** (do NOT touch, even though they look related):

- `src/ludamus/adapters/web/django/views.py` and `forms.py` — their
  `has_conflicts` calls stay as-is; do not migrate them to the
  batched lookup here.
- `AnonymousEnrollmentRepository` in the same enrollment.py — its
  single-user `has_conflicts` path is fine.
- `src/ludamus/links/db/django/companions.py` and the per-owner
  `active_companions` / `occupying_user_ids` queries inside
  `_slots_remaining` — deferred (see Maintenance notes).
- `src/ludamus/pacts/enrollment.py` — the DTOs must not change.
- `tests/unit/test_waitlist_promotion_service.py` — stubs the repo
  protocol; the DTO shape is unchanged, so it needs no edits and
  must stay green.

## Git workflow

- Commit style example:
  `perf(links): batch waitlist promotion state queries`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Add a batched conflict lookup on `SessionManager`

In `src/ludamus/adapters/db/django/models.py`, add
`conflicted_user_ids` to `SessionManager` and reimplement
`has_conflicts` as a delegation so there is a single source of truth
for the overlap semantics:

```python
def conflicted_user_ids(
    self, session: Session, user_ids: list[int]
) -> set[int]:
    if not user_ids:
        return set()
    start = session.agenda_item.start_time
    end = session.agenda_item.end_time
    return set(
        self.get_queryset()
        .filter(
            event_id=session.event_id,
            session_participations__user_id__in=user_ids,
            session_participations__status=(
                SessionParticipationStatus.CONFIRMED
            ),
        )
        .filter(
            Q(
                agenda_item__start_time__gte=start,
                agenda_item__start_time__lt=end,
            )
            | Q(
                agenda_item__end_time__gt=start,
                agenda_item__end_time__lte=end,
            )
        )
        .exclude(id=session.id)
        .values_list("session_participations__user_id", flat=True)
    )

def has_conflicts(self, session: Session, user: UserDTO) -> bool:
    return user.pk in self.conflicted_user_ids(session, [user.pk])
```

Both filter conditions on `session_participations__*` sit in one
`.filter()` call (single join), exactly as today; the
`values_list` selects the matched participation's `user_id` through
that same join, and `set()` deduplicates users with several
conflicting sessions.

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all
pass (existing conflict tests in
`tests/integration/web/chronology/test_session_enroll_page.py` and
the promotion tests cover the delegation).

### Step 2: Use the batched conflict lookup in the promotion loop

In `lock_and_read_state`
(`src/ludamus/links/db/django/enrollment.py`), after `sponsors =
sponsors_by_member(...)`, compute once:

```python
conflicted = Session.objects.conflicted_user_ids(
    session, [p.user_id for p in participations]
)
```

and in the loop replace the per-waiter call with
`has_conflict=participation.user_id in conflicted`. The
`UserDTO.model_validate(user)` argument existed only for this call;
drop it from the loop (keep the `UserDTO` import — `_slots_remaining`
still uses it).

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all
pass, and:

```sh
grep -c "Session.objects.has_conflicts" \
  src/ludamus/links/db/django/enrollment.py
```

→ `1` (only the `AnonymousEnrollmentRepository` usage remains).

### Step 3: Batch the enrollment-config lookups

Still in `src/ludamus/links/db/django/enrollment.py`:

1. Add a private helper that issues at most two `__in` queries for
   all owners at once (Django skips the query entirely for an empty
   `__in` list):

   ```python
   @staticmethod
   def _config_allowances(
       event: Event, owner_emails: set[str]
   ) -> tuple[dict[str, int], dict[str, int]]:
       emails = {email for email in owner_emails if email}
       domains = {
           email.split("@")[1] for email in emails if "@" in email
       }
       configs = event.get_active_enrollment_configs()
       user_allowed: dict[str, int] = {}
       user_rows = UserEnrollmentConfig.objects.filter(
           enrollment_config__in=configs, user_email__in=emails
       ).values_list("user_email", "allowed_slots")
       for email, slots in user_rows:
           user_allowed[email] = user_allowed.get(email, 0) + slots
       domain_allowed: dict[str, int] = {}
       domain_rows = DomainEnrollmentConfig.objects.filter(
           enrollment_config__in=configs, domain__in=domains
       ).values_list("domain", "allowed_slots_per_user")
       for domain, slots in domain_rows:
           domain_allowed[domain] = (
               domain_allowed.get(domain, 0) + slots
           )
       return user_allowed, domain_allowed
   ```

   Key presence in these dicts encodes today's `has_config` flag —
   a config row with 0 slots must still produce a key (the
   `test_restrictive_domain_allowance_holds_seat` case), which the
   summation above preserves.

2. Rewrite `_slots_remaining` to pure dict math for the allowance
   part (the companion/used-slot queries stay). It gains 4
   parameters, so they become keyword-only per repo rules; `event`
   is no longer needed:

   ```python
   @staticmethod
   def _slots_remaining(
       *,
       owner: User,
       event_dto: EventDTO,
       user_allowed: dict[str, int],
       domain_allowed: dict[str, int],
   ) -> int:
       if not owner.email:
           return UNLIMITED_SLOTS
       domain = (
           owner.email.split("@")[1] if "@" in owner.email else ""
       )
       has_config = owner.email in user_allowed or (
           bool(domain) and domain in domain_allowed
       )
       if not has_config:
           return UNLIMITED_SLOTS
       allowed = user_allowed.get(owner.email, 0)
       if domain:
           allowed += domain_allowed.get(domain, 0)
       companions = active_companions(owner.slug)
       members = [
           UserDTO.model_validate(owner),
           *(UserDTO.model_validate(c) for c in companions),
       ]
       used = len(
           EnrollmentParticipationRepository.occupying_user_ids(
               user_ids=[member.pk for member in members],
               event_id=event_dto.pk,
           )
       )
       return max(0, allowed - used)
   ```

3. In `lock_and_read_state`, before the loop, resolve each waiter's
   recipient once and build the allowance dicts:

   ```python
   recipients = {
       p.user.pk: sponsors.get(p.user.pk, p.user)
       for p in participations
   }
   user_allowed, domain_allowed = self._config_allowances(
       event,
       {r.email or "" for r in recipients.values()},
   )
   ```

   In the loop, take `recipient = recipients[user.pk]` and call
   `self._slots_remaining(owner=recipient, event_dto=event_dto,
   user_allowed=user_allowed, domain_allowed=domain_allowed)` under
   the existing `slots_by_owner` memo. Behavior must be identical:
   same DTO fields, same FIFO order, same `UNLIMITED_SLOTS` and
   zero-slot outcomes.

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all
pass, including `test_promotes_within_membership_allowance`,
`test_restrictive_domain_allowance_holds_seat`,
`test_promotes_emailless_waiter_without_membership_limit`, and
`test_slots_remaining_handles_email_without_at_sign`.

### Step 4: Add query-count and conflict-flag regression tests

Extend
`tests/integration/web/chronology/test_waitlist_promotion.py` with a
new class (reuse the existing imports plus `SessionFactory`,
`AgendaItemFactory`, and `PartyMembership`-free companion setup via
`UserFactory(manager=...)`, all from `tests.integration.conftest`):

```python
STATE_QUERIES = 0  # pin after the first run, see below


@pytest.mark.usefixtures("enrollment_config")
class TestPromotionStateQueryCount:
    def _add_waiters(self, session, owner_a, owner_b, count_a):
        ...  # see Test plan for the arrange recipe

    def test_pinned_query_count(
        self, session, agenda_item, enrollment_config,
        django_assert_num_queries,
    ):
        ...
        with DjangoTransaction().atomic():
            with django_assert_num_queries(STATE_QUERIES):
                repo.lock_and_read_state(session.pk)

    def test_count_constant_as_waiters_grow(self, ...):
        ...  # same owners, 2 extra companion waiters,
        ...  # same STATE_QUERIES pin
```

Arrange (both tests share it): 3+ WAITING participations across 2
distinct owners — owner A (a real user with a
`UserEnrollmentConfig` on the active config) waiting themselves plus
one companion created with
`UserFactory(user_type=UserType.CONNECTED, manager=owner_a)`, and
owner B (a real user, no config) waiting. The growth test adds two
more companions under owner A, so the owner set is unchanged and
the pinned count must hold exactly. Enter `DjangoTransaction()
.atomic()` **before** `django_assert_num_queries` so the SAVEPOINT
statement is not counted.

To pin `STATE_QUERIES`: run the test once with the placeholder `0`,
read the executed-query list pytest-django prints on failure,
confirm it contains no repeated per-waiter agenda-overlap query and
no per-config `user_enrollment_config`/`domain_enrollment_config`
lookups, then set the observed constant and add a one-line
breakdown comment next to it.

Also add a conflict-flag behavior test in the same class: give one
waiter a CONFIRMED participation in another session of the same
event whose agenda item copies this session's
`agenda_item.start_time`/`end_time`, leave a second waiter clear,
then assert
`{w.user_id: w.has_conflict for w in state.waiting}` maps the
clashing waiter to `True` and the clear one to `False`.

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all
pass, including the 3 new tests.

### Step 5: Full gate

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run check` → exit 0
(mypy strict, import-linter, pylint) and
`PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all pass.

## Test plan

- New integration tests (links code → integration, never unit) in
  `tests/integration/web/chronology/test_waitlist_promotion.py`,
  modeled on the existing `TestPromotionRepositoryEdges` class:
  - pinned `django_assert_num_queries(STATE_QUERIES)` for 3 waiters
    across 2 owners (one owner with a config);
  - identical pin with 2 extra waiters for the same owners — the
    regression this plan exists for (previously each waiter added a
    conflict query);
  - conflict flags: overlapping CONFIRMED session → `True`, clear
    waiter → `False`.
- Existing behavior tests double as the equivalence suite:
  `TestFillFreedSeats` (allowance math, zero-slot domain config,
  emailless owner) and `TestPromotionRepositoryEdges` (party
  memoization, malformed email) must pass unmodified.
- Unit suite (`mise run test:unit`) must pass unmodified — the repo
  protocol and DTOs are unchanged.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "Session.objects.has_conflicts"` over
  `src/ludamus/links/db/django/enrollment.py` returns `1` (the
  anonymous-enrollment path only)
- [ ] `grep -n "UserEnrollmentConfig.objects.filter"` over
  `src/ludamus/links/db/django/enrollment.py` shows exactly one
  match, inside `_config_allowances` (same for
  `DomainEnrollmentConfig.objects.filter`)
- [ ] `grep -c "def has_conflicts" src/ludamus/adapters/db/django/models.py`
  returns `1` and `grep -c "def conflicted_user_ids"
  src/ludamus/adapters/db/django/models.py` returns `1`
- [ ] `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` exits 0,
  including the 3 new tests
- [ ] `PATH="$(pwd)/.venv/bin:$PATH" mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts no longer match the live code (drift) — especially
  the `gte/lt` / `gt/lte` overlap window in `has_conflicts`.
- The batched `conflicted_user_ids` cannot reproduce
  `has_conflicts` semantics exactly: the new conflict-flag test (or
  any existing conflict test) shows a flag differing from what
  `Session.objects.has_conflicts` returns for the same waiter.
  Time-overlap windows are subtle — report, do not tweak operators.
- The pinned query count is not identical between the base and
  grown-waiters scenarios after the change.
- Any existing test shows DTO output ordering or values changed
  (FIFO order, `owner_slots_remaining`, `has_conflict`,
  recipient fields).
- mypy/pylint failures whose fix requires a noqa/type-ignore or a
  file outside the in-scope list.

## Maintenance notes

- Deliberately deferred: `active_companions` and
  `occupying_user_ids` still run once per distinct owner *with a
  config* inside `_slots_remaining`. Batching those needs a
  cross-owner used-slots query keyed by leader; do it only if
  profiling shows config-holding owners in the tens per session.
- `has_conflicts` now delegates to `conflicted_user_ids`, so any
  future change to conflict semantics (e.g. counting OFFERED seats
  as blocking) lands in one place and automatically covers both the
  single and batched paths — reviewers should reject a patch that
  re-forks them.
- If the pinned `STATE_QUERIES` constant breaks later, first check
  whether a new per-waiter query crept into the loop before bumping
  the number.
- Reviewers should scrutinize: the `values_list` in
  `conflicted_user_ids` reads the user id through the same join the
  filter created (the query-count and conflict-flag tests prove it),
  and key-presence in the allowance dicts faithfully replaces the
  old `has_config` boolean for zero-slot configs.
