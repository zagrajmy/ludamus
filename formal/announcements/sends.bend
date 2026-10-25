# One published event and the subscribers' announcement, against two runs of
# the sweep that sends it.
#
# announce_published_events lists the pending events (subscribers_announced_at
# is null), then for each one, in its own transaction, stamps it with
# mark_announced and notifies every subscriber. mark_announced is a plain
# update: it neither filters on the stamp still being null nor checks how many
# rows it changed. The DBOS schedule and the `announce_published_events`
# management command (the manual fallback) can run the sweep at the same time.

import Base

# A run of the sweep: Idle, or holding the event in its pending list.
type Run is Data:
  Idle{}
  Listed{}

type Lane is Data:
  R1{}
  R2{}

# stamped: subscribers_announced_at is set. sent: how many times subscribers
# were notified.
type Published is Data:
  Published{stamped: Bool, sent: Nat, r1: Run, r2: Run}

type Op is Data:
  # list_pending_announcements: the event is listed while it is unstamped.
  Scan{lane: Lane}
  # The per-event transaction: mark_announced, then notify every subscriber.
  Send{lane: Lane}

def start() -> Published:
  Published{False{}, 0n, Idle{}, Idle{}}

def run(l: Lane, e: Published) -> Run:
  match l:
    case R1{}:
      match e:
        case Published{s, n, a, b}:
          a
    case R2{}:
      match e:
        case Published{s, n, a, b}:
          b

def set_run(l: Lane, e: Published, r: Run) -> Published:
  match l:
    case R1{}:
      match e:
        case Published{s, n, a, b}:
          Published{s, n, r, b}
    case R2{}:
      match e:
        case Published{s, n, a, b}:
          Published{s, n, a, r}

def stamped(e: Published) -> Bool:
  match e:
    case Published{s, n, a, b}:
      s

def announce(e: Published) -> Published:
  match e:
    case Published{s, n, a, b}:
      Published{True{}, 1n+n, a, b}

def pick(c: Bool, +yes: Published, +no: Published) -> Published:
  match c:
    case True{}:
      yes
    case False{}:
      no

def send(+l: Lane, +e: Published, r: Run) -> Published:
  match r:
    case Idle{}:
      e
    case Listed{}:
      set_run(l, announce(e), Idle{})

def step(+e: Published, op: Op) -> Published:
  match op:
    case Scan{+l}:
      pick(Bool.not(stamped(e)), set_run(l, e, Listed{}), e)
    case Send{+l}:
      send(l, e, run(l, e))

def replay(ops: List<Op>, e: Published) -> Published:
  match ops:
    case Nil{}:
      e
    case Con{op, rest}:
      replay(rest, step(e, op))

def sent_twice(e: Published) -> Bool:
  match e:
    case Published{s, n, a, b}:
      Nat.is_gt(n, 1n)
