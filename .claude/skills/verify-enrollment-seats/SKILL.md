---
name: verify-enrollment-seats
description: Check the Bend proofs about enrollment seats before and after changing how a seat is taken, held, offered, claimed, dropped or promoted. Use when a change touches `_process_enrollments` / `_check_and_create_enrollment` / `_is_capacity_invalid` / `_hold_member_seats` in `adapters/web/django/views.py`, `WaitlistPromotionService` in `mills/enrollment.py`, `AnonymousEnrollmentService.enroll` / `cancel` in `mills/enrollment_anonymous.py`, `select_promotable_parties` in `specs/enrollment.py`, `ParticipationPromotionRepository` / `AnonymousEnrollmentRepository` in `links/db/django/enrollment.py`, `conflicted_user_ids` / `has_conflicts` / `seats_left` / `enrolled_count` on `Session` in `links/db/django/models.py`, `OCCUPYING_PARTICIPATION_STATUSES`, or any `select_for_update` on the enrollment path. Also use for "can this double-book someone", "can this overbook a session", or a race between two signups.
---

# Verify enrollment seats

`formal/enrollment/` models how sessions hand out seats, in
[Bend](https://github.com/bendlang/bend), a language whose checker verifies
proofs. It covers three properties that tests rarely reach:

- **Capacity: proven.** No session ever seats more people than
  `participants_limit`. Breaking it puts more people at a table than it has
  chairs. The proof holds for every limit, any number of people and requests,
  and every order of events, at any length.
- **No double booking: proven.** Nobody holds CONFIRMED seats in two
  sessions whose agenda items overlap. Breaking it takes a seat from someone
  on the waiting list and leaves an empty chair at one of the two tables. The
  proof holds for every order of enrolls, holds, promotions, claims, cancels
  and drops, interleaved however two transactions can be, under the lock
  order below.
- **Passes never overspent: proven.** A pass owner never has more distinct
  people seated across the event than they hold passes, however two requests
  that spend them interleave.

Both rest on one lock order, taken by every transaction that decides a seat
before it reads what it decides on: the `Session` row, then
`lock_seat_holders` (`links/db/django/enrollment.py`), one `SELECT … FOR
UPDATE OF` on `User` ordered by pk over the people whose seats it decides,
their pass owners, and the session's waiters when it may refill the session
in the same transaction. `docs/agents/architecture.md` (event noun) says why
it cannot deadlock.

## Run it

```sh
mise run formal
```

The first run downloads Bend 2.0.37 into `~/.cache/ludamus/` and checks it
against the sha256 that bend-lang.com's installer pins. A run takes about six
seconds. Each file in `formal/enrollment/expected` prints one of:

- `ok`: the file checks.
- `BROKEN`: a law no longer has a proof.
- `GONE`: a finding's trace no longer double-books.

Bend's own error follows each failure. The task exits non-zero unless every
file checks. CI runs the same script in the `formal` job of
`.github/workflows/ci.yml` on every pull request, so a change that breaks a
proof, or fixes a finding without updating it, fails there too. `mise run
formal formal/enrollment` checks one area; `formal/programme` and
`formal/announcements` model accepting proposals and the announcement sweep
the same way.

The seat model is also run against the real enroll view:
`tests/integration/web/chronology/test_seats_model_differential.py` drives
both with the same steps. After editing `seats.bend`, regenerate its compiled
copy with `FORMAL_REGEN=1 mise run formal formal/enrollment`; the check
reports `STALE` until you do. [docs/VERIFICATION.md](../../../docs/VERIFICATION.md)
maps every verification tool to the layer it covers.

| File | What it is |
| --- | --- |
| `seats.bend` | One session's seats: `taken` rows, and `held` seats the lock holder will write. Ops: `Check`, `Commit`, `Free`, `Claim`, `Join` |
| `schedule.bend` | One person's rows in sessions A and B, which overlap, with each session's lock and the person's lock (`lock_p`, held while either session has a write pending). Ops: `Enroll`, `Hold`, `Promote`, `Commit`, `Join`, `Cancel`, `Claim`, `Drop` |
| `allowance.bend` | One pass owner's household across the event, against two enroll requests into different sessions, with the owner's lock (`owner_free`). Ops: `Check`, `Commit` |
| `LAWS.bend` | The claims: `capacity`, `no_double_booking`, `allowance_never_overspent`, plus serial runs (`enroll_seats_serial_first`, `conflict_blocks_serial_enroll`, `allowance_seats_serial_second`, `allowance_refuses_serial_third`) that pin the models' checks to the checks in the code from both sides |
| `PROOF.bend` | The proofs. Each is an invariant over the committed rows and the write in flight that holds at the start and every op keeps |
| `finding_*.bend` | One known bug each, when there is one: a law that a trace reaching it exists, proven by the trace itself. None is open for enrollment |
| `seats.gen.mjs`, `replay_seats.mjs` | `seats.bend` compiled to JS, and the Node runner the differential test calls |

## Known findings

None of the enrollment models has an open finding. Three were closed by
taking the lock order above (plan 021):

1. **Two requests at once double-booked a person** (`Enroll A, Enroll B,
   Commit A, Commit B`): each locked only its own `Session` row. Both now
   lock the person's `User` row first, so the second reads the first's seat.
   `fill_freed_seats` racing an enroll is closed the same way: it locks the
   waiters before `has_conflict`.
2. **A held or offered seat got past the conflict check** (`Hold A, Commit
   A, Enroll B, Commit B, Claim A`): `conflicted_user_ids` counted only
   CONFIRMED rows. It now counts `OCCUPYING_PARTICIPATION_STATUSES`, and
   `_claim` rechecks under the locks; a clash drops the clashing members'
   offer (`reason="conflict"`) and the seat rolls on.
3. **Two requests at once seated more people than the owner holds passes**:
   the form's `can_enroll_users` ran before any lock. The enroll view now
   asks again under the owner's lock (`AllowanceCheck.passes`) and refuses
   with the form's message.

The Postgres tests in
`tests/integration/web/chronology/test_enrollment_locking.py` replay 1 and 3
and the promotion race with two connections; they fail on the code before
the locks.


## Does my change touch the model?

Each op names the code it stands for in its comment.

| Model | Code |
| --- | --- |
| `seats.Check{want}`, `schedule.Enroll` | `_process_enrollments` → `_lock_seat_holders` → `_is_capacity_invalid` → `_check_and_create_enrollment`. Also `AnonymousEnrollmentService.enroll` (`lock_seating`, `lock_seat_holders`, `has_conflicts`, `is_full`) |
| `seats.Check{want}`, `schedule.Hold` | `_hold_member_seats` → `WaitlistPromotionService.hold_seat` |
| `seats.Check{want}`, `schedule.Promote` | `fill_freed_seats` → `lock_and_read_state` (Session row, the WAITING read, then `lock_seat_holders` on the waiters) → `select_promotable_parties` |
| `Commit` | the writes and COMMIT of any check |
| `seats.Free`, `schedule.Cancel` / `Drop` | `_handle_cancellation`, anonymous `cancel`, `decline_offer` / `expire_offer` → `drop` |
| `Claim` | `claim_offer` / `claim_member_offer` → `_read_locked_party` (Session row) → `_claim` → `lock_seat_holders`, `conflicted_user_ids`, then `drop` or `mark_claimed` |
| `seats.fits` | `Session.seats_left` |
| `schedule.has_conflict` | `SessionManager.conflicted_user_ids` |
| `held`, `lock_a` / `lock_b` | `select_for_update` on the `Session` row |
| `schedule.lock_p`, `allowance.owner_free` | `lock_seat_holders`: the `User` rows of the people decided and their pass owners |
| `allowance.Check` | `AllowanceCheck.passes` under the locks in `_process_enrollments` (the form's earlier `can_enroll_users` only refuses sooner) |

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
  `Some` waits. In `schedule.bend`, `lock_a` / `lock_b` do the same, and a
  check also waits while `lock_p` (the person's row) is held. To drop a
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
  always free. Its proof covers every interleaving of those ops, but timetable
  moves (an agenda item moved onto another while seats are held) are out:
  `_claim` rechecks for that case, and nothing else does.
- The allowance model has one owner, two companions and two requests, and
  covers the enroll gate. Promotion applies the same rule
  (`owner_slots_remaining` less the waiters without `holds_event_seat`),
  read under the same owner lock, but is not modelled;
  `test_promotion_allowance_properties.py` checks on the real database
  that it admits exactly whom the gate admits.
- Deadlock freedom is argued, not modelled: the lock order in
  `docs/agents/architecture.md`. The Postgres tests exercise it.
- Left out: parties and the whole-party rule; guests as separate people;
  enrollment windows; presenter and shadowban skips; offer deadlines;
  notifications.
