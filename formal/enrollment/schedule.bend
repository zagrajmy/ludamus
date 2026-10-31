# One person's rows in two sessions, A and B, whose agenda items overlap.
#
# Seats are left to seats.bend: here every session has room, so a check fails
# only on a lock, the row's status, or a time conflict.
#
# Every transaction that decides one of P's seats takes the Session row lock,
# then P's User row lock (lock_seat_holders), and only then runs its check; it
# keeps both until it commits. A pending write in either session therefore
# means its transaction holds P's lock: `lock_p` is that lock.

import Base

type Side is Data:
  A{}
  B{}

# SessionParticipation.status, Out when the person has no row.
type Status is Data:
  Out{}
  Waiting{}
  Offered{}
  Confirmed{}

# Per session: Unlocked, or the row the request holding `select_for_update`
# on the Session row (and P's User row) will write for P when it commits.
type Lock is Data:
  Unlocked{}
  Writes{to: Status}

type Person is Data:
  Person{a: Status, b: Status, lock_a: Lock, lock_b: Lock}

type Op is Data:
  # _process_enrollments for "enroll", or AnonymousEnrollmentService.enroll:
  # the Session row lock, lock_seat_holders, has_conflicts, then the write.
  Enroll{side: Side}
  # _hold_member_seats -> hold_seat for an ACCEPT_INVITES member: inside the
  # same batch, after the same locks and has_conflicts check; an OFFERED row.
  Hold{side: Side}
  # fill_freed_seats: lock_and_read_state locks the Session row and the
  # waiters, then reads has_conflict from conflicted_user_ids; AUTO confirms,
  # OFFER_CLAIM (`offer`) offers.
  Promote{side: Side, offer: Bool}
  # The lock holder's writes and COMMIT; both locks go.
  Commit{side: Side}
  # Choice "waitlist", or create_waiting: no conflict check. The code takes
  # P's lock here too; the model asks only for the Session lock, which lets
  # more runs through, never fewer.
  Join{side: Side}
  # _handle_cancellation, anonymous cancel; the same over-approximation.
  Cancel{side: Side}
  # claim_offer / claim_member_offer -> _claim: the Session row lock (inside
  # the offer read), lock_seat_holders, then conflicted_user_ids. A clash drops
  # the offer; otherwise mark_claimed. Write and commit run under both locks,
  # so nothing of P's moves in between: one step.
  Claim{side: Side}
  # decline_offer / expire_offer -> drop, under the Session row lock.
  Drop{side: Side}

def start() -> Person:
  Person{Out{}, Out{}, Unlocked{}, Unlocked{}}

def pick(c: Bool, +yes: Person, +no: Person) -> Person:
  match c:
    case True{}:
      yes
    case False{}:
      no

def is_confirmed(s: Status) -> Bool:
  match s:
    case Confirmed{}:
      True{}
    case _:
      False{}

# OCCUPYING_PARTICIPATION_STATUSES: a held chair counts as a seat.
def is_occupying(s: Status) -> Bool:
  match s:
    case Confirmed{}:
      True{}
    case Offered{}:
      True{}
    case _:
      False{}

def is_offered(s: Status) -> Bool:
  match s:
    case Offered{}:
      True{}
    case _:
      False{}

def is_out(s: Status) -> Bool:
  match s:
    case Out{}:
      True{}
    case _:
      False{}

def is_waiting(s: Status) -> Bool:
  match s:
    case Waiting{}:
      True{}
    case _:
      False{}

def is_unlocked(l: Lock) -> Bool:
  match l:
    case Unlocked{}:
      True{}
    case _:
      False{}

def row(side: Side, p: Person) -> Status:
  match side:
    case A{}:
      match p:
        case Person{a, b, la, lb}:
          a
    case B{}:
      match p:
        case Person{a, b, la, lb}:
          b

def lock(side: Side, p: Person) -> Lock:
  match side:
    case A{}:
      match p:
        case Person{a, b, la, lb}:
          la
    case B{}:
      match p:
        case Person{a, b, la, lb}:
          lb

def other(side: Side) -> Side:
  match side:
    case A{}:
      B{}
    case B{}:
      A{}

# SessionManager.conflicted_user_ids / has_conflicts: occupying rows.
def has_conflict(+side: Side, +p: Person) -> Bool:
  is_occupying(row(other(side), p))

# P's User row lock: free while no transaction is mid-write for P.
def lock_p(p: Person) -> Bool:
  match p:
    case Person{a, b, la, lb}:
      Bool.not(is_unlocked(la) && is_unlocked(lb))

def set_row(side: Side, p: Person, s: Status) -> Person:
  match side:
    case A{}:
      match p:
        case Person{a, b, la, lb}:
          Person{s, b, la, lb}
    case B{}:
      match p:
        case Person{a, b, la, lb}:
          Person{a, s, la, lb}

def set_lock(side: Side, p: Person, l: Lock) -> Person:
  match side:
    case A{}:
      match p:
        case Person{a, b, la, lb}:
          Person{a, b, l, lb}
    case B{}:
      match p:
        case Person{a, b, la, lb}:
          Person{a, b, la, l}

# Lock the side's Session row and P's row, then check, and remember the
# write; a request that fails a check rolls back and leaves no trace. A free
# lock_p means the side's Session lock is free too.
def reserve(+side: Side, +p: Person, ok: Bool, to: Status) -> Person:
  pick(Bool.not(lock_p(p)) && (Bool.not(has_conflict(side, p)) && ok),
    set_lock(side, p, Writes{to}), p)

# The claim's recheck: a clash releases the offer, else it is confirmed.
def claimed(+side: Side, +p: Person) -> Person:
  pick(has_conflict(side, p), set_row(side, p, Out{}),
    set_row(side, p, Confirmed{}))

def promoted(offer: Bool) -> Status:
  match offer:
    case True{}:
      Offered{}
    case False{}:
      Confirmed{}

def commit(+side: Side, +p: Person, l: Lock) -> Person:
  match l:
    case Unlocked{}:
      p
    case Writes{to}:
      set_lock(side, set_row(side, p, to), Unlocked{})

def step(+p: Person, e: Op) -> Person:
  match e:
    case Enroll{+side}:
      +s = row(side, p)
      reserve(side, p, is_out(s) || is_waiting(s), Confirmed{})
    case Hold{+side}:
      reserve(side, p, is_out(row(side, p)), Offered{})
    case Promote{+side, offer}:
      reserve(side, p, is_waiting(row(side, p)), promoted(offer))
    case Commit{+side}:
      commit(side, p, lock(side, p))
    case Join{+side}:
      pick(is_unlocked(lock(side, p)) && is_out(row(side, p)),
        set_row(side, p, Waiting{}), p)
    case Cancel{+side}:
      pick(is_unlocked(lock(side, p)) && Bool.not(is_out(row(side, p))),
        set_row(side, p, Out{}), p)
    case Claim{+side}:
      pick(Bool.not(lock_p(p)) && is_offered(row(side, p)), claimed(side, p), p)
    case Drop{+side}:
      pick(is_unlocked(lock(side, p)) && is_offered(row(side, p)),
        set_row(side, p, Out{}), p)

def replay(ops: List<Op>, p: Person) -> Person:
  match ops:
    case Nil{}:
      p
    case Con{e, rest}:
      replay(rest, step(p, e))

# CONFIRMED in both A and B, which overlap.
def double_booked(p: Person) -> Bool:
  match p:
    case Person{a, b, la, lb}:
      is_confirmed(a) && is_confirmed(b)
