# One person's rows in two sessions, A and B, whose agenda items overlap.
#
# Seats are left to seats.bend: here every session has room, so a check fails
# only on the lock, the row's status, or a time conflict.

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
# on the Session row will write for this person when it commits.
type Lock is Data:
  Unlocked{}
  Writes{to: Status}

type Person is Data:
  Person{a: Status, b: Status, lock_a: Lock, lock_b: Lock}

type Op is Data:
  # _process_enrollments for "enroll", or AnonymousEnrollmentService.enroll:
  # has_conflicts, then the Session row lock and the write.
  Enroll{side: Side}
  # _hold_member_seats -> hold_seat for an ACCEPT_INVITES member: the same
  # has_conflicts check, then an OFFERED row.
  Hold{side: Side}
  # fill_freed_seats: lock_and_read_state reads has_conflict from
  # conflicted_user_ids; AUTO confirms, OFFER_CLAIM (`offer`) offers.
  Promote{side: Side, offer: Bool}
  # The lock holder's writes and COMMIT.
  Commit{side: Side}
  # Choice "waitlist", or create_waiting: no conflict check.
  Join{side: Side}
  # _handle_cancellation, anonymous cancel.
  Cancel{side: Side}
  # claim_offer / claim_member_offer -> _claim -> mark_claimed: locks the
  # OFFERED rows, not the Session row, and checks only the deadline.
  Claim{side: Side}
  # decline_offer / expire_offer -> drop.
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

# SessionManager.conflicted_user_ids / has_conflicts: CONFIRMED rows only.
def has_conflict(+side: Side, +p: Person) -> Bool:
  is_confirmed(row(other(side), p))

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

# Lock the side's Session row and remember the write; a request that fails a
# check rolls back and leaves no trace.
def reserve(+side: Side, +p: Person, ok: Bool, to: Status) -> Person:
  pick(is_unlocked(lock(side, p)) && (Bool.not(has_conflict(side, p)) && ok),
    set_lock(side, p, Writes{to}), p)

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
      pick(is_offered(row(side, p)), set_row(side, p, Confirmed{}), p)
    case Drop{+side}:
      pick(is_offered(row(side, p)), set_row(side, p, Out{}), p)

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
