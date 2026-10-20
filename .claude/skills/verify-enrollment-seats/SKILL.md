---
name: verify-enrollment-seats
description: Check the Bend proofs about enrollment seats before and after changing how a seat is taken, held, offered, claimed, dropped or promoted. Use when a change touches `_process_enrollments` / `_check_and_create_enrollment` / `_is_capacity_invalid` / `_hold_member_seats` in `adapters/web/django/views.py`, `WaitlistPromotionService` in `mills/enrollment.py`, `AnonymousEnrollmentService.enroll` / `cancel` in `mills/enrollment_anonymous.py`, `select_promotable_parties` in `specs/enrollment.py`, `ParticipationPromotionRepository` / `AnonymousEnrollmentRepository` in `links/db/django/enrollment.py`, `conflicted_user_ids` / `has_conflicts` / `seats_left` / `enrolled_count` on `Session` in `links/db/django/models.py`, `OCCUPYING_PARTICIPATION_STATUSES`, or any `select_for_update` on the enrollment path. Also use for "can this double-book someone", "can this overbook a session", or a race between two signups.
---

# Verify enrollment seats

`formal/enrollment/` models how sessions hand out seats, in
[Bend](https://github.com/bendlang/bend), a language whose checker verifies
proofs. It covers two properties that tests rarely reach:

- **Capacity: proven.** No session ever seats more people than
  `participants_limit`. Breaking it puts more people at a table than it has
  chairs. The proof holds for every limit, any number of people and requests,
  and every order of events, at any length.
- **No double booking: broken.** Nobody should hold CONFIRMED seats in two
  sessions whose agenda items overlap. Breaking it takes a seat from someone
  on the waiting list and leaves an empty chair at one of the two tables. Two
  ways to break it are on `main` today. Each is written as a concrete trace
  that Bend computes to a double booking.

## Run it

```sh
mise run formal:enrollment
```

The first run downloads Bend 2.0.37 into `~/.cache/ludamus/` and checks it
against the sha256 that bend-lang.com's installer pins. A run takes about six
seconds. Each file in `formal/enrollment/expected` prints one of:

- `ok`: the file checks.
- `BROKEN`: a law no longer has a proof.
- `GONE`: a finding's trace no longer double-books.

Bend's own error follows each failure. The task exits non-zero unless every
file checks.

| File | What it is |
| --- | --- |
| `seats.bend` | One session's seats: `taken` rows, and `held` seats the lock holder will write. Ops: `Check`, `Commit`, `Free`, `Claim`, `Join` |
| `schedule.bend` | One person's rows in sessions A and B, which overlap, with each session's lock. Ops: `Enroll`, `Hold`, `Promote`, `Commit`, `Join`, `Cancel`, `Claim`, `Drop` |
| `LAWS.bend` | The claims: `capacity`, and `conflict_blocks_serial_enroll`, which pins the model's conflict check to the code's |
| `PROOF.bend` | The proofs. Capacity: `taken + held <= limit` holds at the start and every op keeps it |
| `finding_*.bend` | One known bug each: a law that a double-booking trace exists, proven by the trace itself |

## Known findings

Both are open on `main`. The finding files check for as long as the bugs
exist.

1. **`finding_two_requests.bend`: two requests at once double-book a
   person.** Trace: `Enroll A, Enroll B, Commit A, Commit B`. Person P sends an
   enroll for session A and one for session B, which overlap. Each request
   locks only its own `Session` row (`select_for_update` in
   `_process_enrollments`). Each runs `has_conflicts` before the other commits,
   so each sees no conflict, and both commit. `lock_and_read_state` locks one
   session too, so `fill_freed_seats` can race an enroll the same way. This
   finding comes from the model. It has not been reproduced on Postgres.
2. **`finding_offered_seat.bend`: a held or offered seat gets past the
   conflict check.** Trace: `Hold A, Commit A, Enroll B, Commit B, Claim A`. A
   leader holds a seat for P in A (`hold_seat`), or the waiting list offers P
   one (OFFER_CLAIM). `conflicted_user_ids` counts only CONFIRMED rows, so P's
   OFFERED seat in A does not count, and P enrolls in B. P then claims A, and
   `_claim` → `mark_claimed` never rechecks. It was reproduced against the real
   views and services: the enroll POST answered "Enrolled", `claim_offer`
   succeeded, and both rows were `confirmed`.

The fix for finding 2 is to count OFFERED rows in the conflict check, or to
recheck conflicts in `_claim`. Finding 1 needs a lock that every session the
person could clash with shares. One option is `select_for_update` on the
person's `User` row before `has_conflicts`, taken in user-id order when a
batch seats several people.

## Does my change touch the model?

Each op names the code it stands for in its comment.

| Model | Code |
| --- | --- |
| `seats.Check{want}`, `schedule.Enroll` | `_process_enrollments` → `_is_capacity_invalid` → `_check_and_create_enrollment`. Also `AnonymousEnrollmentService.enroll` (`lock_seating`, `is_full`) |
| `seats.Check{want}`, `schedule.Hold` | `_hold_member_seats` → `WaitlistPromotionService.hold_seat` |
| `seats.Check{want}`, `schedule.Promote` | `fill_freed_seats` → `lock_and_read_state` → `select_promotable_parties` |
| `Commit` | the writes and COMMIT of any check |
| `seats.Free`, `schedule.Cancel` / `Drop` | `_handle_cancellation`, anonymous `cancel`, `decline_offer` / `expire_offer` → `drop` |
| `Claim` | `claim_offer` / `claim_member_offer` → `_claim` → `mark_claimed` |
| `seats.fits` | `Session.seats_left` |
| `schedule.has_conflict` | `SessionManager.conflicted_user_ids` |
| `held`, `lock_a` / `lock_b` | `select_for_update` on the `Session` row |

The model must change when your change does any of these:

- adds, removes or moves a lock;
- changes what a check reads, such as which statuses count;
- splits or merges transactions;
- adds a new path that writes a `SessionParticipation` row.

A rename, logging, or a change to messages and notifications leaves the model
alone. Run the check anyway: it takes seconds.

## Update the model

Make one op do what the code now does, at the same grain:

- **One op is what runs before another transaction can commit in between.** A
  transaction that reads, then writes, with no lock that blocks the other
  writer, is two ops: a check that records the write, and a `Commit` that
  makes it.
- **A failed check leaves the state as it was.** The request rolled back.
- **Locks.** In `seats.bend`, `held` is the session lock: a `Check` while it is
  `Some` waits. In `schedule.bend`, `lock_a` / `lock_b` do the same. To drop a
  lock, let the check go through while the lock is held, and give each
  in-flight write somewhere to live, such as a list.
- **Never weaken a law to get a pass.** Keep `capacity` as stated.

## When something fails

**`BROKEN PROOF.bend`.** Either the law became false or the proof is stale.
Find out which before you edit anything:

1. Look for a counterexample. In a scratch file beside the model, write a
   short op list that should overbook, and state its result as a computed law
   proven by `{==}`:

   ```python
   import Base
   import ./seats.bend as Seats

   law overbooks:
     ops = {[Seats.Check{2n}, Seats.Commit{}] : List<Seats.Op>}
     s = Seats.replay(ops, 1n, Seats.start())
     {Nat.is_le(Seats.taken(s), 1n) == False{} : Bool}

   def overbooks():
     {==}
   ```

   If `bend` prints ALL PROOFS CHECK, the law is false: report a real bug,
   with the ops in the code's words, and delete the scratch file.
2. If you find no counterexample, the proof needs the new step. The error's
   `Location` names the def that failed (`keep_check`, `keep_free`, …). Its
   `expected` and `observed` lines show the goal. `?name` in place of a term
   prints the goal there.

**`GONE finding_*.bend`.** The trace no longer double-books:

1. If the code was fixed, update the model to match, then delete the finding
   file and its line in `expected`. Add the law it broke to `LAWS.bend`, such
   as `for ops: List<Schedule.Op>` with `double_booked(...) == False{}`, and
   prove it in `PROOF.bend`. One dead trace proves nothing: other paths can
   still reach the bug, and only a proof for every op list shows they don't.
2. If the code did not change in that way, the model drifted from the code.
   Fix the model, not the trace.

**Reproducing in the real code.** The pattern that confirmed finding 2 was an
integration test under `tests/integration/web/chronology/`. Create an OFFERED
`SessionParticipation` with a `claim_token` in one session. POST `enroll` to
an overlapping session the user does not host. Call
`Services().waitlist_promotion.claim_offer(token=...)`, then read both rows.
Run it with `mise run test:py -- -n 0 <file>`, not bare pytest. A race like
finding 1 only reproduces on Postgres (`mise run test:postgres`) with two
connections. Do not change product code unless the user asks.

## Writing Bend here

- Values are affine. A parameter used twice needs `+` (`+limit: Nat`), and so
  does a pattern field (`case Con{+e, rest}`).
- A list literal needs its type: `{[S.Enroll{S.A{}}] : List<S.Op>}`.
- There is no `if`: match on `True{}` / `False{}`, through a helper when the
  value is computed. A `match` takes only a parameter or a pattern variable.
- `Event` is a Base type, so model ops are named `Op`.
- `bend guide` prints the language guide, and `bend base Nat` prints a part
  of Base.
- `bend PROOF.bend --verdict` rechecks with Bend's Lean-proven kernel. It
  builds Lean v4.34.0 on first use, so the gate does not run it.

## What this does not cover

- Capacity is proven about the ledger in `seats.bend`, where each op's change
  to the seat count is read off the code by hand. It is not derived from the
  rows themselves. The proof treats one session at a time with a fixed
  `participants_limit`. Organizer edits to the limit and unscheduling are out.
- The schedule model has one person, two overlapping sessions, and seats
  always free. The findings show that a path exists. They are not a search,
  so other paths to the same bug may exist.
- Left out: parties and the whole-party rule; membership allowance
  (`owner_slots_remaining`), which is also checked outside any shared lock and
  may have the same race as finding 1; guests as separate people; enrollment
  windows; presenter and shadowban skips; offer deadlines; notifications.
