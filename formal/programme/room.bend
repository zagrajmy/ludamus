# Two proposals, P and Q, accepted into the same space and time slot.
#
# ProposalAcceptPageView loads the session and refuses one that is no longer
# PENDING; accept_session then runs list_overlapping_in_space and, inside its
# transaction, writes the session and creates the AgendaItem. Nothing locks the
# space, so the overlap check reads only what other accepts have committed.
# AgendaItem.session is one-to-one, so a second item for one session fails.

import Base

type Proposal is Data:
  P{}
  Q{}

type Lane is Data:
  L1{}
  L2{}

# A request in flight: Idle, or the proposal it will place at commit.
type Request is Data:
  Idle{}
  Places{proposal: Proposal}

# placed_p / placed_q: an AgendaItem in this space and slot exists.
# crashed: a commit hit the one-to-one AgendaItem.session (a 500).
type Room is Data:
  Room{placed_p: Bool, placed_q: Bool, crashed: Bool, l1: Request, l2: Request}

type Op is Data:
  # _load (status PENDING) and list_overlapping_in_space(exclude_session_pk).
  Accept{lane: Lane, proposal: Proposal}
  # _sessions.update + _agenda_items.create, then COMMIT.
  Commit{lane: Lane}

def start() -> Room:
  Room{False{}, False{}, False{}, Idle{}, Idle{}}

def pick(c: Bool, +yes: Room, +no: Room) -> Room:
  match c:
    case True{}:
      yes
    case False{}:
      no

def placed(p: Proposal, r: Room) -> Bool:
  match p:
    case P{}:
      match r:
        case Room{a, b, c, l1, l2}:
          a
    case Q{}:
      match r:
        case Room{a, b, c, l1, l2}:
          b

def other(p: Proposal) -> Proposal:
  match p:
    case P{}:
      Q{}
    case Q{}:
      P{}

def lane(l: Lane, r: Room) -> Request:
  match l:
    case L1{}:
      match r:
        case Room{a, b, c, l1, l2}:
          l1
    case L2{}:
      match r:
        case Room{a, b, c, l1, l2}:
          l2

def is_idle(q: Request) -> Bool:
  match q:
    case Idle{}:
      True{}
    case _:
      False{}

def set_lane(l: Lane, r: Room, q: Request) -> Room:
  match l:
    case L1{}:
      match r:
        case Room{a, b, c, l1, l2}:
          Room{a, b, c, q, l2}
    case L2{}:
      match r:
        case Room{a, b, c, l1, l2}:
          Room{a, b, c, l1, q}

def place(p: Proposal, r: Room) -> Room:
  match p:
    case P{}:
      match r:
        case Room{a, b, c, l1, l2}:
          Room{True{}, b, c, l1, l2}
    case Q{}:
      match r:
        case Room{a, b, c, l1, l2}:
          Room{a, True{}, c, l1, l2}

def crash(r: Room) -> Room:
  match r:
    case Room{a, b, c, l1, l2}:
      Room{a, b, True{}, l1, l2}

def commit(+l: Lane, +r: Room, q: Request) -> Room:
  match q:
    case Idle{}:
      r
    case Places{+p}:
      set_lane(l, pick(placed(p, r), crash(r), place(p, r)), Idle{})

def step(+r: Room, e: Op) -> Room:
  match e:
    case Accept{+l, +p}:
      free = Bool.not(placed(p, r)) && Bool.not(placed(other(p), r))
      ok = is_idle(lane(l, r)) && free
      pick(ok, set_lane(l, r, Places{p}), r)
    case Commit{+l}:
      commit(l, r, lane(l, r))

def replay(ops: List<Op>, r: Room) -> Room:
  match ops:
    case Nil{}:
      r
    case Con{e, rest}:
      replay(rest, step(r, e))

# Two agenda items in one space and slot.
def double_booked(r: Room) -> Bool:
  match r:
    case Room{a, b, c, l1, l2}:
      a && b

def crashed(r: Room) -> Bool:
  match r:
    case Room{a, b, c, l1, l2}:
      c
