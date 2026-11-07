# 021: Serialise seat decisions per person and per pass owner

Priority: P1. Effort: M. Depends on: the containment fix to
`conflicted_user_ids` (branch `fix/enrollment-conflict-containment-and-duration-digits`).

## Problem

Three open findings in `docs/VERIFICATION.md` share one cause: every writer on
the enrollment path locks only the `Session` row it writes into, but the two
invariants it enforces are about a *person* (no two confirmed seats in
overlapping sessions) and a *pass owner* (no more distinct seated people than
the owner holds passes). Two transactions on two sessions share no lock, so
each reads a state the other is about to change.

| Finding (`formal/enrollment/finding_*.bend`) | Trace |
| --- | --- |
| `finding_two_requests` | P enrolls in A and in B at once; each `has_conflicts` runs before the other commits; both commit. `fill_freed_seats` races an enroll the same way. |
| `finding_offered_seat` | P holds an OFFERED seat in A; `conflicted_user_ids` counts only CONFIRMED rows, so P enrolls in B; P then claims A and `_claim` never rechecks. No race needed; reproduced against the views. |
| `finding_allowance_race` | The owner's form check (`can_enroll_users`) runs before any lock; two requests sponsor two companions into two sessions, each reads {owner}, both commit: 3 people on 2 passes. |

## Design: one lock order, taken before any check

Every transaction that decides a seat takes, in this order, and only then
reads the state it decides on:

1. **The `Session` row** (`select_for_update(of=("self",))`), as today.
2. **The `User` rows of everyone whose seat the transaction decides, plus the
   pass owner of each of them** (`effective_slot_owner`: the sponsoring
   manager for a login-less companion, the person themselves otherwise), in
   one statement ordered by primary key:
   `User.objects.select_for_update(of=("self",)).filter(pk__in=ids).order_by("pk")`.
3. Then the checks: `has_conflicts`, the allowance, capacity; then the writes.

Why it cannot deadlock: a transaction holds at most one `Session` lock and
asks for it first; it never asks for a `Session` row while holding `User`
rows, and it asks for `User` rows in a single ordered statement. The wait-for
graph has edges only from "holds Session, wants User", so a cycle would need a
transaction that holds a `User` row and waits for a `Session` row, which the
order forbids. The refill after a cancellation (`fill_freed_seats`) is already
a separate transaction after commit, so it does not nest.

Why it is sufficient: the two races are both "read under lock X, write under
lock X, where the invariant is keyed by Y". Keying the lock by the person
(conflicts) and the owner (allowance) makes the second transaction read the
first one's committed write.

On SQLite (dev, the e2e seed, most tests) `select_for_update` is a no-op and
`transaction_mode = "IMMEDIATE"` serialises every writer, so the protocol
holds trivially; only Postgres exercises it, which is why the race tests are
`@pytest.mark.postgres`.

## Changes

1. **Repository helper** in `links/db/django/enrollment.py`, exposed through
   the pacts protocols the enrollment mills already use:
   `lock_seat_holders(*, user_ids: Iterable[int]) -> None` takes the `User`
   row locks for the given people and their effective slot owners
   (`sponsors_by_member` already knows the owner of a companion), ordered by
   pk. One statement; nothing is returned because the point is the lock.
2. **Enroll view** (`_process_enrollments`): after the `Session` lock and
   before `_is_capacity_invalid`, lock the seat holders of every request
   (enroll, waitlist, cancel, held seats) and of the guests' host. Then
   re-run the allowance check that the form ran (`can_enroll_users` with the
   same inputs) under the lock; on failure raise the same `RedirectError`
   with the message the form would have shown. The pre-check in the form
   stays as the early answer; the check under the lock is the authoritative
   one.
3. **Promotion** (`lock_and_read_state`): after the `Session` lock and the
   WAITING read, lock the waiters and their owners before computing
   `has_conflict` and `owner_slots_remaining`.
4. **Conflicts count held seats**: `conflicted_user_ids` filters on
   `OCCUPYING_PARTICIPATION_STATUSES` (CONFIRMED and OFFERED) instead of
   CONFIRMED only. An offer is a held chair; treating it as occupying matches
   how capacity already counts it. Compose with the containment fix: the
   overlap predicate becomes `other.start < end AND other.end > start` over
   occupying rows.
5. **Claim rechecks**: `_claim` (`claim_offer`, `claim_member_offer`) takes
   the `Session` lock and the party's `User` locks, then runs
   `has_conflicts` for each member; a conflicting member's offer is dropped
   (the seat rolls on through `fill_freed_seats` after commit) and the claim
   returns `ClaimResult(success=False, reason="conflict", ...)`, which the
   claim page renders with a translated message ("You hold a seat in a
   session that overlaps this one; leave it first."). `decline_offer` and
   `expire_offer` take the `Session` lock too so every path to a row's status
   agrees on the order.
6. **Anonymous enrollment** (`AnonymousEnrollmentService.enroll` /
   `lock_seating`): same order; anonymous users are `User` rows too.
7. **Bend**: `schedule.bend` gains a per-person lock (`lock_p`) that `Enroll`,
   `Hold`, `Promote` and `Claim` must take before their check and that
   `Commit`/`Drop` release; `Claim` rechecks conflicts; `is_occupying`
   replaces `is_confirmed` in `has_conflict`. `allowance.bend` gains an
   owner lock that `Check` takes and `Commit` releases. The three
   `finding_*.bend` files go; `LAWS.bend` states `no_double_booking` (for
   all ops) and `allowance_never_overspent` (for all ops), and `PROOF.bend`
   proves them. `expected/` is updated. The sandbox cannot download Bend
   (GitHub releases are blocked), so CI's `formal` job is the gate; write the
   proofs the way `PROOF.bend` proves `capacity` and iterate on CI output.
8. **Docs**: remove the three rows from `docs/VERIFICATION.md` "Open
   findings"; update the "Known findings" and lock table in
   `.claude/skills/verify-enrollment-seats/SKILL.md`; add the lock order to
   `docs/agents/architecture.md` under the event noun's enrollment note.

## Tests (write first)

- `tests/integration/web/chronology/test_enrollment_locking.py`,
  `@pytest.mark.postgres`, `transactional_db`: two threads, each its own
  connection. (a) Double booking: P enrolls in A and B (overlapping) at once;
  exactly one request ends CONFIRMED, the other is skipped with the time
  conflict message. (b) Allowance: owner with 2 passes seated; two requests
  sponsor First into A and Second into B at once; exactly one succeeds, the
  other redirects with the allowance message. (c) Promotion vs enroll: P waits
  in A and enrolls in B while a cancel in A promotes; P never ends confirmed
  in both. Use a barrier so both threads are inside the transaction before
  either commits; the pre-fix code must fail these.
- SQLite-level tests for the logic: an OFFERED seat in an overlapping session
  blocks an enroll (`has_conflicts`); a claim with a conflicting confirmed seat
  fails with `reason="conflict"` and drops the offer; the allowance recheck
  under the lock refuses a third person; the serial Hypothesis properties in
  `tests/integration/web/chronology/test_*properties*.py` still pass.
- `test_seats_model_differential.py` keeps passing (`seats.bend` is
  unchanged).

## STOP conditions

- If Postgres is unavailable locally, the race tests run only in CI; say so
  in the PR and do not weaken them to run on SQLite.
- If a Bend proof does not close after three CI rounds, keep the finding file
  for the unproven law, state the law with a TODO-free `# unproven` note in
  the PR, and report it; do not delete a finding whose trace still computes.
