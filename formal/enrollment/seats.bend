# One session's seats, as its SessionParticipation rows hold them.
#
# Every event touches the rows of one session, and every lock on the enrollment
# path is that session's row lock, so one session is the whole story for
# capacity. `limit` is Session.participants_limit; organizer edits to it are
# out of scope, so it stays fixed for the whole run.

import Base

# taken: committed OCCUPYING_PARTICIPATION_STATUSES rows (CONFIRMED, OFFERED)
# held:  seats the request holding `select_for_update` on the Session row will
#        write when it commits; None while nobody holds the lock
type Seats is Data:
  Seats{taken: Nat, held: Maybe<&2, Nat>}

type Op is Data:
  # Lock the Session row, then check the seats left before writing `want`
  # occupying rows: _process_enrollments (_is_capacity_invalid; enroll, held
  # seats, guests, a whole batch), AnonymousEnrollmentService.enroll
  # (lock_seating, is_full), fill_freed_seats (lock_and_read_state,
  # select_promotable_parties against seats_left).
  Check{want: Nat}
  # The lock holder's writes and COMMIT.
  Commit{}
  # One occupying row deleted: _handle_cancellation, anonymous cancel,
  # decline_offer / expire_offer -> drop (a party is one Free per member).
  Free{}
  # claim_offer -> mark_claimed: OFFERED becomes CONFIRMED, still one seat.
  Claim{}
  # A WAITING row: holds no seat.
  Join{}

def start() -> Seats:
  Seats{0n, None{}}

def taken(s: Seats) -> Nat:
  match s:
    case Seats{t, h}:
      t

# Session.seats_left >= want, as `taken + want <= limit`.
def fits(+limit: Nat, +taken: Nat, +want: Nat) -> Bool:
  Nat.is_le(Nat.add(taken, want), limit)

# A failed check rolls back: no lock kept, nothing written.
def reserve(ok: Bool, taken: Nat, want: Nat) -> Seats:
  match ok:
    case True{}:
      Seats{taken, Some{want}}
    case False{}:
      Seats{taken, None{}}

def check(+limit: Nat, +taken: Nat, held: Maybe<&2, Nat>, +want: Nat) -> Seats:
  match held:
    case None{}:
      reserve(fits(limit, taken, want), taken, want)
    case Some{k}:
      # Another request holds the lock: this one waits.
      Seats{taken, Some{k}}

def commit(taken: Nat, held: Maybe<&2, Nat>) -> Seats:
  match held:
    case None{}:
      Seats{taken, None{}}
    case Some{k}:
      Seats{Nat.add(taken, k), None{}}

def free(taken: Nat, held: Maybe<&2, Nat>) -> Seats:
  match taken:
    case 0n:
      Seats{0n, held}
    case 1n+t:
      Seats{t, held}

def step(+limit: Nat, s: Seats, e: Op) -> Seats:
  match s:
    case Seats{t, h}:
      match e:
        case Check{want}:
          check(limit, t, h, want)
        case Commit{}:
          commit(t, h)
        case Free{}:
          free(t, h)
        case Claim{}:
          Seats{t, h}
        case Join{}:
          Seats{t, h}

def replay(ops: List<Op>, +limit: Nat, s: Seats) -> Seats:
  match ops:
    case Nil{}:
      s
    case Con{e, rest}:
      replay(rest, limit, step(limit, s, e))
