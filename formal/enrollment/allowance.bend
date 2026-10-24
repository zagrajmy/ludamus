# One pass owner's household across an event, against the enroll requests
# that spend the passes.
#
# A pass covers one distinct person per event. The enroll form checks the
# allowance (can_enroll_users inside form.is_valid) before _process_enrollments
# takes any lock, and the lock it then takes is the Session row of the session
# being enrolled into. Two requests into two sessions share no lock at all.

import Base

# The owner and two login-less companions they sponsor.
type Member is Data:
  Owner{}
  First{}
  Second{}

# Who already holds an occupying seat somewhere in the event.
type Seated is Data:
  Seated{owner: Bool, first: Bool, second: Bool}

# A request in flight: Idle, or the member it read as fitting and will seat.
type Request is Data:
  Idle{}
  Adds{who: Member}

# Two requests at once, each into its own session.
type Lane is Data:
  L1{}
  L2{}

type Household is Data:
  Household{seated: Seated, l1: Request, l2: Request}

type Op is Data:
  # form.is_valid -> can_enroll_users: |already seated ∪ {who}| <= allowed.
  Check{lane: Lane, who: Member}
  # _process_enrollments writes the seat and commits.
  Commit{lane: Lane}

def start() -> Household:
  Household{Seated{False{}, False{}, False{}}, Idle{}, Idle{}}

def b2n(b: Bool) -> Nat:
  match b:
    case True{}:
      1n
    case False{}:
      0n

def count(s: Seated) -> Nat:
  match s:
    case Seated{o, f, c}:
      Nat.add(b2n(o), Nat.add(b2n(f), b2n(c)))

def seat(who: Member, s: Seated) -> Seated:
  match who:
    case Owner{}:
      match s:
        case Seated{o, f, c}:
          Seated{True{}, f, c}
    case First{}:
      match s:
        case Seated{o, f, c}:
          Seated{o, True{}, c}
    case Second{}:
      match s:
        case Seated{o, f, c}:
          Seated{o, f, True{}}

def is_idle(r: Request) -> Bool:
  match r:
    case Idle{}:
      True{}
    case _:
      False{}

def pick(c: Bool, +yes: Household, +no: Household) -> Household:
  match c:
    case True{}:
      yes
    case False{}:
      no

def lane(l: Lane, h: Household) -> Request:
  match l:
    case L1{}:
      match h:
        case Household{s, a, b}:
          a
    case L2{}:
      match h:
        case Household{s, a, b}:
          b

def set_lane(l: Lane, h: Household, r: Request) -> Household:
  match l:
    case L1{}:
      match h:
        case Household{s, a, b}:
          Household{s, r, b}
    case L2{}:
      match h:
        case Household{s, a, b}:
          Household{s, a, r}

def seated(h: Household) -> Seated:
  match h:
    case Household{s, a, b}:
      s

def set_seated(h: Household, s: Seated) -> Household:
  match h:
    case Household{old, a, b}:
      Household{s, a, b}

def commit(+l: Lane, +h: Household, r: Request) -> Household:
  match r:
    case Idle{}:
      h
    case Adds{who}:
      set_lane(l, set_seated(h, seat(who, seated(h))), Idle{})

def step(+allowed: Nat, +h: Household, e: Op) -> Household:
  match e:
    case Check{+l, +who}:
      fits = Nat.is_le(count(seat(who, seated(h))), allowed)
      pick(is_idle(lane(l, h)) && fits, set_lane(l, h, Adds{who}), h)
    case Commit{+l}:
      commit(l, h, lane(l, h))

def replay(ops: List<Op>, +allowed: Nat, h: Household) -> Household:
  match ops:
    case Nil{}:
      h
    case Con{e, rest}:
      replay(rest, allowed, step(allowed, h, e))

# More distinct people seated than the owner holds passes for.
def over_allowance(+allowed: Nat, h: Household) -> Bool:
  Nat.is_gt(count(seated(h)), allowed)
