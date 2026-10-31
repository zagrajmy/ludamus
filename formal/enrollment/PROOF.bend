# The proof of LAWS.bend.
#
# Capacity: the seats taken plus the seats the lock holder has reserved never
# exceed the limit. It holds at the start, and every op keeps it: a check
# reserves only what fits, a commit turns the reservation into taken seats, a
# free only lowers the count, and a check that finds the lock held waits.
#
# no_double_booking and allowance_never_overspent follow the same shape below:
# an invariant over the committed rows and the write in flight, kept by every
# op. The serial laws are single runs, checked by computing them.

import Base
import ./seats.bend as Seats
import ./schedule.bend as Schedule
import ./allowance.bend as Household
import ./LAWS.bend as Laws

# T(b): the truth of b as a type, so a computed check is a proof by conversion.
def T(b: Bool) -> Data:
  match b:
    case True{}:
      Unit
    case False{}:
      Empty

def T.eq(+b: Bool, w: T(b)) -> {b == True{} : Bool}:
  match b:
    case True{}:
      {==}
    case False{}:
      Empty.absurd({False{} == True{} : Bool}, w)

# Arithmetic
# ----------

def le_zero(l: Nat) -> T(Nat.is_le(0n, l)):
  match l:
    case 0n:
      Unit{}
    case 1n+p:
      Unit{}

def le_succ(x: Nat, l: Nat, w: T(Nat.is_le(1n+x, l))) -> T(Nat.is_le(x, l)):
  match x:
    case 0n:
      le_zero(l)
    case 1n+xp:
      match l:
        case 0n:
          Empty.absurd(T(Nat.is_le(1n+xp, 0n)), w)
        case 1n+lp:
          le_succ(xp, lp, w)

def le_add(t: Nat, -k: Nat, l: Nat, w: T(Nat.is_le(Nat.add(t, k), l)))
  -> T(Nat.is_le(t, l)):
  match t:
    case 0n:
      le_zero(l)
    case 1n+tp:
      match l:
        case 0n:
          Empty.absurd(T(Nat.is_le(1n+tp, 0n)), w)
        case 1n+lp:
          le_add(tp, k, lp, w)

# Invariant
# ---------

def inv_at(+limit: Nat, t: Nat, h: Maybe<&2, Nat>) -> Bool:
  match h:
    case None{}:
      Nat.is_le(t, limit)
    case Some{k}:
      Nat.is_le(Nat.add(t, k), limit)

def inv(+limit: Nat, s: Seats.Seats) -> Bool:
  match s:
    case Seats.Seats{t, h}:
      inv_at(limit, t, h)

def keep_reserve(+ok: Bool, -limit: Nat, -t: Nat, -want: Nat,
  e: {ok == Seats.fits(limit, t, want) : Bool}, w: T(Nat.is_le(t, limit)))
  -> T(inv(limit, Seats.reserve(ok, t, want))):
  match ok:
    case True{}:
      %e : T(_)
      Unit{}
    case False{}:
      w

def keep_check(+limit: Nat, +t: Nat, h: Maybe<&2, Nat>, +want: Nat,
  w: T(inv_at(limit, t, h))) -> T(inv(limit, Seats.check(limit, t, h, want))):
  match h:
    case None{}:
      keep_reserve(Seats.fits(limit, t, want), limit, t, want, {==}, w)
    case Some{k}:
      w

def keep_commit(-limit: Nat, -t: Nat, h: Maybe<&2, Nat>,
  w: T(inv_at(limit, t, h))) -> T(inv(limit, Seats.commit(t, h))):
  match h:
    case None{}:
      w
    case Some{k}:
      w

def keep_free(+limit: Nat, t: Nat, h: Maybe<&2, Nat>,
  w: T(inv_at(limit, t, h))) -> T(inv(limit, Seats.free(t, h))):
  match t:
    case 0n:
      w
    case 1n+tp:
      match h:
        case None{}:
          le_succ(tp, limit, w)
        case Some{k}:
          le_succ(Nat.add(tp, k), limit, w)

def keep(+limit: Nat, s: Seats.Seats, e: Seats.Op, w: T(inv(limit, s)))
  -> T(inv(limit, Seats.step(limit, s, e))):
  match s:
    case Seats.Seats{t, h}:
      match e:
        case Seats.Check{want}:
          keep_check(limit, t, h, want, w)
        case Seats.Commit{}:
          keep_commit(limit, t, h, w)
        case Seats.Free{}:
          keep_free(limit, t, h, w)
        case Seats.Claim{}:
          w
        case Seats.Join{}:
          w

def within(+limit: Nat, s: Seats.Seats, w: T(inv(limit, s)))
  -> {Nat.is_le(Seats.taken(s), limit) == True{} : Bool}:
  match s:
    case Seats.Seats{+t, h}:
      match h:
        case None{}:
          T.eq(Nat.is_le(t, limit), w)
        case Some{k}:
          T.eq(Nat.is_le(t, limit), le_add(t, k, limit, w))

def keep_all(ops: List<Seats.Op>, +limit: Nat, +s: Seats.Seats,
  w: T(inv(limit, s)))
  -> {Nat.is_le(Seats.taken(Seats.replay(ops, limit, s)), limit) == True{} : Bool}:
  match ops:
    case Nil{}:
      within(limit, s, w)
    case Con{+e, rest}:
      keep_all(rest, limit, Seats.step(limit, s, e), keep(limit, s, e, w))

def Laws.capacity(limit, ops):
  keep_all(ops, limit, Seats.start(), le_zero(limit))

def Laws.conflict_blocks_serial_enroll():
  {==}

def Laws.allowance_refuses_serial_third():
  {==}

def Laws.enroll_seats_serial_first():
  {==}

# No double booking
# -----------------
#
# The argument: P never holds occupying rows in both sessions, and a write
# pending in one session (its transaction holds P's lock) means P holds no
# occupying row and no pending write in the other. It holds at the start, and
# every op keeps it: a check takes P's lock only while the other side is idle
# and finds no occupying row there, a commit lands where the other side cannot
# have moved, a claim rechecks, and joins, cancels and drops only write rows
# that hold no seat.

def free(s: Schedule.Status) -> Bool:
  Bool.not(Schedule.is_occupying(s))

def apart(a: Schedule.Status, b: Schedule.Status) -> Bool:
  Bool.not(Schedule.is_occupying(a) && Schedule.is_occupying(b))

def sinv(a: Schedule.Status, b: Schedule.Status, la: Schedule.Lock,
  lb: Schedule.Lock) -> Bool:
  match la:
    case Schedule.Unlocked{}:
      match lb:
        case Schedule.Unlocked{}:
          apart(a, b)
        case Schedule.Writes{t}:
          free(a)
    case Schedule.Writes{t}:
      match lb:
        case Schedule.Unlocked{}:
          free(b)
        case Schedule.Writes{u}:
          False{}

def pinv(p: Schedule.Person) -> Bool:
  match p:
    case Schedule.Person{a, b, la, lb}:
      sinv(a, b, la, lb)

# A row that holds no seat on the right sits beside anything.
def apart_free(a: Schedule.Status, -b: Schedule.Status, wb: T(free(b)))
  -> T(apart(a, b)):
  match a:
    case Schedule.Out{}:
      Unit{}
    case Schedule.Waiting{}:
      Unit{}
    case Schedule.Offered{}:
      wb
    case Schedule.Confirmed{}:
      wb

# Enroll, Hold, Promote on A: only with P's lock free and no seat in B.
def hold_a(-a: Schedule.Status, b: Schedule.Status, ok: Bool,
  -to: Schedule.Status,
  w: T(sinv(a, b, Schedule.Unlocked{}, Schedule.Unlocked{})))
  -> T(pinv(Schedule.reserve(Schedule.A{},
    Schedule.Person{a, b, Schedule.Unlocked{}, Schedule.Unlocked{}}, ok, to))):
  match b:
    case Schedule.Out{}:
      match ok:
        case True{}:
          Unit{}
        case False{}:
          w
    case Schedule.Waiting{}:
      match ok:
        case True{}:
          Unit{}
        case False{}:
          w
    case Schedule.Offered{}:
      w
    case Schedule.Confirmed{}:
      w

def hold_b(a: Schedule.Status, -b: Schedule.Status, ok: Bool,
  -to: Schedule.Status,
  w: T(sinv(a, b, Schedule.Unlocked{}, Schedule.Unlocked{})))
  -> T(pinv(Schedule.reserve(Schedule.B{},
    Schedule.Person{a, b, Schedule.Unlocked{}, Schedule.Unlocked{}}, ok, to))):
  match a:
    case Schedule.Out{}:
      match ok:
        case True{}:
          Unit{}
        case False{}:
          w
    case Schedule.Waiting{}:
      match ok:
        case True{}:
          Unit{}
        case False{}:
          w
    case Schedule.Offered{}:
      w
    case Schedule.Confirmed{}:
      w

def keep_lock_p(la: Schedule.Lock, lb: Schedule.Lock, side: Schedule.Side, a: Schedule.Status,
  b: Schedule.Status, ok: Bool, -to: Schedule.Status, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.reserve(side, Schedule.Person{a, b, la, lb}, ok, to))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match lb:
        case Schedule.Writes{t}:
          w
        case Schedule.Unlocked{}:
          match side:
            case Schedule.A{}:
              hold_a(a, b, ok, to, w)
            case Schedule.B{}:
              hold_b(a, b, ok, to, w)

def keep_commit_a(la: Schedule.Lock, lb: Schedule.Lock, -a: Schedule.Status,
  b: Schedule.Status, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Commit{Schedule.A{}}))):
  match la:
    case Schedule.Unlocked{}:
      w
    case Schedule.Writes{t}:
      match lb:
        case Schedule.Writes{u}:
          match w:
        case Schedule.Unlocked{}:
          apart_free(t, b, w)

def keep_commit_b(lb: Schedule.Lock, la: Schedule.Lock, a: Schedule.Status,
  -b: Schedule.Status, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Commit{Schedule.B{}}))):
  match lb:
    case Schedule.Unlocked{}:
      w
    case Schedule.Writes{t}:
      match la:
        case Schedule.Writes{u}:
          match w:
        case Schedule.Unlocked{}:
          match a:
            case Schedule.Out{}:
              Unit{}
            case Schedule.Waiting{}:
              Unit{}
            case Schedule.Offered{}:
              match w:
            case Schedule.Confirmed{}:
              match w:

# A's row turns into one that holds no seat, with lock_a free.
def unseat_a(-b: Schedule.Status, lb: Schedule.Lock)
  -> T(sinv(Schedule.Out{}, b, Schedule.Unlocked{}, lb)):
  match lb:
    case Schedule.Unlocked{}:
      Unit{}
    case Schedule.Writes{t}:
      Unit{}

def wait_a(-b: Schedule.Status, lb: Schedule.Lock)
  -> T(sinv(Schedule.Waiting{}, b, Schedule.Unlocked{}, lb)):
  match lb:
    case Schedule.Unlocked{}:
      Unit{}
    case Schedule.Writes{t}:
      Unit{}

# B's row turns into one that holds no seat, with lock_b free.
def unseat_b(a: Schedule.Status, la: Schedule.Lock)
  -> T(sinv(a, Schedule.Out{}, la, Schedule.Unlocked{})):
  match la:
    case Schedule.Unlocked{}:
      apart_free(a, Schedule.Out{}, Unit{})
    case Schedule.Writes{t}:
      Unit{}

def wait_b(a: Schedule.Status, la: Schedule.Lock)
  -> T(sinv(a, Schedule.Waiting{}, la, Schedule.Unlocked{})):
  match la:
    case Schedule.Unlocked{}:
      apart_free(a, Schedule.Waiting{}, Unit{})
    case Schedule.Writes{t}:
      Unit{}

def keep_join_a(la: Schedule.Lock, a: Schedule.Status, -b: Schedule.Status,
  lb: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Join{Schedule.A{}}))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match a:
        case Schedule.Out{}:
          wait_a(b, lb)
        case Schedule.Waiting{}:
          w
        case Schedule.Offered{}:
          w
        case Schedule.Confirmed{}:
          w

def keep_join_b(lb: Schedule.Lock, b: Schedule.Status, a: Schedule.Status,
  la: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Join{Schedule.B{}}))):
  match lb:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match b:
        case Schedule.Out{}:
          wait_b(a, la)
        case Schedule.Waiting{}:
          w
        case Schedule.Offered{}:
          w
        case Schedule.Confirmed{}:
          w

def keep_cancel_a(la: Schedule.Lock, a: Schedule.Status, -b: Schedule.Status,
  lb: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Cancel{Schedule.A{}}))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match a:
        case Schedule.Out{}:
          w
        case Schedule.Waiting{}:
          unseat_a(b, lb)
        case Schedule.Offered{}:
          unseat_a(b, lb)
        case Schedule.Confirmed{}:
          unseat_a(b, lb)

def keep_cancel_b(lb: Schedule.Lock, b: Schedule.Status, a: Schedule.Status,
  la: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Cancel{Schedule.B{}}))):
  match lb:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match b:
        case Schedule.Out{}:
          w
        case Schedule.Waiting{}:
          unseat_b(a, la)
        case Schedule.Offered{}:
          unseat_b(a, la)
        case Schedule.Confirmed{}:
          unseat_b(a, la)

def keep_drop_a(la: Schedule.Lock, a: Schedule.Status, -b: Schedule.Status,
  lb: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Drop{Schedule.A{}}))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match a:
        case Schedule.Out{}:
          w
        case Schedule.Waiting{}:
          w
        case Schedule.Offered{}:
          unseat_a(b, lb)
        case Schedule.Confirmed{}:
          w

def keep_drop_b(lb: Schedule.Lock, b: Schedule.Status, a: Schedule.Status,
  la: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Drop{Schedule.B{}}))):
  match lb:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match b:
        case Schedule.Out{}:
          w
        case Schedule.Waiting{}:
          w
        case Schedule.Offered{}:
          unseat_b(a, la)
        case Schedule.Confirmed{}:
          w

# A claim confirms only beside a row that holds no seat; else it releases.
def keep_claim_a(la: Schedule.Lock, lb: Schedule.Lock, a: Schedule.Status,
  b: Schedule.Status, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Claim{Schedule.A{}}))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match lb:
        case Schedule.Writes{t}:
          w
        case Schedule.Unlocked{}:
          match a:
            case Schedule.Out{}:
              w
            case Schedule.Waiting{}:
              w
            case Schedule.Confirmed{}:
              w
            case Schedule.Offered{}:
              match b:
                case Schedule.Out{}:
                  Unit{}
                case Schedule.Waiting{}:
                  Unit{}
                case Schedule.Offered{}:
                  Unit{}
                case Schedule.Confirmed{}:
                  Unit{}

def keep_claim_b(la: Schedule.Lock, lb: Schedule.Lock, b: Schedule.Status,
  a: Schedule.Status, w: T(sinv(a, b, la, lb)))
  -> T(pinv(Schedule.step(Schedule.Person{a, b, la, lb},
    Schedule.Claim{Schedule.B{}}))):
  match la:
    case Schedule.Writes{t}:
      w
    case Schedule.Unlocked{}:
      match lb:
        case Schedule.Writes{t}:
          w
        case Schedule.Unlocked{}:
          match b:
            case Schedule.Out{}:
              w
            case Schedule.Waiting{}:
              w
            case Schedule.Confirmed{}:
              w
            case Schedule.Offered{}:
              match a:
                case Schedule.Out{}:
                  Unit{}
                case Schedule.Waiting{}:
                  Unit{}
                case Schedule.Offered{}:
                  Unit{}
                case Schedule.Confirmed{}:
                  Unit{}

def keep_s(p: Schedule.Person, e: Schedule.Op, w: T(pinv(p)))
  -> T(pinv(Schedule.step(p, e))):
  match p:
    case Schedule.Person{+a, +b, +la, +lb}:
      match e:
        case Schedule.Enroll{+side}:
          +s = Schedule.row(side, Schedule.Person{a, b, la, lb})
          keep_lock_p(la, lb, side, a, b,
            Schedule.is_out(s) || Schedule.is_waiting(s), Schedule.Confirmed{}, w)
        case Schedule.Hold{+side}:
          keep_lock_p(la, lb, side, a, b,
            Schedule.is_out(Schedule.row(side, Schedule.Person{a, b, la, lb})),
            Schedule.Offered{}, w)
        case Schedule.Promote{+side, offer}:
          keep_lock_p(la, lb, side, a, b,
            Schedule.is_waiting(Schedule.row(side, Schedule.Person{a, b, la, lb})),
            Schedule.promoted(offer), w)
        case Schedule.Commit{side}:
          match side:
            case Schedule.A{}:
              keep_commit_a(la, lb, a, b, w)
            case Schedule.B{}:
              keep_commit_b(lb, la, a, b, w)
        case Schedule.Join{side}:
          match side:
            case Schedule.A{}:
              keep_join_a(la, a, b, lb, w)
            case Schedule.B{}:
              keep_join_b(lb, b, a, la, w)
        case Schedule.Cancel{side}:
          match side:
            case Schedule.A{}:
              keep_cancel_a(la, a, b, lb, w)
            case Schedule.B{}:
              keep_cancel_b(lb, b, a, la, w)
        case Schedule.Claim{side}:
          match side:
            case Schedule.A{}:
              keep_claim_a(la, lb, a, b, w)
            case Schedule.B{}:
              keep_claim_b(la, lb, b, a, w)
        case Schedule.Drop{side}:
          match side:
            case Schedule.A{}:
              keep_drop_a(la, a, b, lb, w)
            case Schedule.B{}:
              keep_drop_b(lb, b, a, la, w)

def single(a: Schedule.Status, b: Schedule.Status, la: Schedule.Lock,
  lb: Schedule.Lock, w: T(sinv(a, b, la, lb)))
  -> {Schedule.double_booked(Schedule.Person{a, b, la, lb}) == False{} : Bool}:
  match a:
    case Schedule.Out{}:
      {==}
    case Schedule.Waiting{}:
      {==}
    case Schedule.Offered{}:
      {==}
    case Schedule.Confirmed{}:
      match b:
        case Schedule.Out{}:
          {==}
        case Schedule.Waiting{}:
          {==}
        case Schedule.Offered{}:
          {==}
        case Schedule.Confirmed{}:
          match la:
            case Schedule.Unlocked{}:
              match lb:
                case Schedule.Unlocked{}:
                  match w:
                case Schedule.Writes{t}:
                  match w:
            case Schedule.Writes{t}:
              match lb:
                case Schedule.Unlocked{}:
                  match w:
                case Schedule.Writes{u}:
                  match w:

def keep_all_s(ops: List<Schedule.Op>, +p: Schedule.Person, w: T(pinv(p)))
  -> {Schedule.double_booked(Schedule.replay(ops, p)) == False{} : Bool}:
  match ops:
    case Nil{}:
      match p:
        case Schedule.Person{a, b, la, lb}:
          single(a, b, la, lb, w)
    case Con{+e, rest}:
      keep_all_s(rest, Schedule.step(p, e), keep_s(p, e, w))

def Laws.no_double_booking(ops):
  keep_all_s(ops, Schedule.start(), Unit{})

# Allowance never overspent
# -------------------------
#
# The argument: the people seated fit the owner's passes, and a request in
# flight (it holds the owner's lock) fits them with its person added, while
# the other request is idle. It holds at the start, and every op keeps it: a
# check waits for the lock and reserves only who fits, and a commit seats the
# one person its check counted.

def T.and_fst(x: Bool, -y: Bool, w: T(x && y)) -> T(x):
  match x:
    case True{}:
      Unit{}
    case False{}:
      w

def T.and_snd(x: Bool, -y: Bool, w: T(x && y)) -> T(y):
  match x:
    case True{}:
      w
    case False{}:
      match w:

def T.and_true(x: Bool, w: T(x)) -> T(x && True{}):
  match x:
    case True{}:
      Unit{}
    case False{}:
      w

def hinv_l(+allowed: Nat, +s: Household.Seated, l1: Household.Request,
  l2: Household.Request) -> Bool:
  match l1:
    case Household.Idle{}:
      match l2:
        case Household.Idle{}:
          Nat.is_le(Household.count(s), allowed)
        case Household.Adds{who}:
          Nat.is_le(Household.count(s), allowed)
            && Nat.is_le(Household.count(Household.seat(who, s)), allowed)
    case Household.Adds{who}:
      match l2:
        case Household.Idle{}:
          Nat.is_le(Household.count(s), allowed)
            && Nat.is_le(Household.count(Household.seat(who, s)), allowed)
        case Household.Adds{other}:
          False{}

def hinv(+allowed: Nat, h: Household.Household) -> Bool:
  match h:
    case Household.Household{s, l1, l2}:
      hinv_l(allowed, s, l1, l2)

def reserve_fit(ok: Bool, l: Household.Lane, +allowed: Nat,
  +s: Household.Seated, +who: Household.Member,
  e: {ok == Nat.is_le(Household.count(Household.seat(who, s)), allowed) : Bool},
  w: T(Nat.is_le(Household.count(s), allowed)))
  -> T(hinv(allowed, Household.pick(ok,
    Household.set_lane(l,
      Household.Household{s, Household.Idle{}, Household.Idle{}},
      Household.Adds{who}),
    Household.Household{s, Household.Idle{}, Household.Idle{}}))):
  match ok:
    case False{}:
      w
    case True{}:
      match l:
        case Household.L1{}:
          %e : T(Nat.is_le(Household.count(s), allowed) && _)
          T.and_true(Nat.is_le(Household.count(s), allowed), w)
        case Household.L2{}:
          %e : T(Nat.is_le(Household.count(s), allowed) && _)
          T.and_true(Nat.is_le(Household.count(s), allowed), w)

def keep_owner_check(l1: Household.Request, l2: Household.Request, +allowed: Nat,
  +s: Household.Seated, l: Household.Lane, +who: Household.Member,
  w: T(hinv_l(allowed, s, l1, l2)))
  -> T(hinv(allowed, Household.step(allowed, Household.Household{s, l1, l2},
    Household.Check{l, who}))):
  match l1:
    case Household.Adds{x}:
      w
    case Household.Idle{}:
      match l2:
        case Household.Adds{x}:
          w
        case Household.Idle{}:
          reserve_fit(
            Nat.is_le(Household.count(Household.seat(who, s)), allowed),
            l, allowed, s, who, {==}, w)

def seat_first(l1: Household.Request, l2: Household.Request, +allowed: Nat,
  +s: Household.Seated, w: T(hinv_l(allowed, s, l1, l2)))
  -> T(hinv(allowed, Household.step(allowed, Household.Household{s, l1, l2},
    Household.Commit{Household.L1{}}))):
  match l1:
    case Household.Idle{}:
      w
    case Household.Adds{+x}:
      match l2:
        case Household.Adds{y}:
          match w:
        case Household.Idle{}:
          T.and_snd(Nat.is_le(Household.count(s), allowed),
            Nat.is_le(Household.count(Household.seat(x, s)), allowed), w)

def seat_second(l2: Household.Request, l1: Household.Request, +allowed: Nat,
  +s: Household.Seated, w: T(hinv_l(allowed, s, l1, l2)))
  -> T(hinv(allowed, Household.step(allowed, Household.Household{s, l1, l2},
    Household.Commit{Household.L2{}}))):
  match l2:
    case Household.Idle{}:
      w
    case Household.Adds{+x}:
      match l1:
        case Household.Adds{y}:
          match w:
        case Household.Idle{}:
          T.and_snd(Nat.is_le(Household.count(s), allowed),
            Nat.is_le(Household.count(Household.seat(x, s)), allowed), w)

def keep_seat(l: Household.Lane, l1: Household.Request,
  l2: Household.Request, +allowed: Nat, +s: Household.Seated,
  w: T(hinv_l(allowed, s, l1, l2)))
  -> T(hinv(allowed, Household.step(allowed, Household.Household{s, l1, l2},
    Household.Commit{l}))):
  match l:
    case Household.L1{}:
      seat_first(l1, l2, allowed, s, w)
    case Household.L2{}:
      seat_second(l2, l1, allowed, s, w)

def keep_h(+allowed: Nat, h: Household.Household, e: Household.Op,
  w: T(hinv(allowed, h))) -> T(hinv(allowed, Household.step(allowed, h, e))):
  match h:
    case Household.Household{+s, +l1, +l2}:
      match e:
        case Household.Check{l, who}:
          keep_owner_check(l1, l2, allowed, s, l, who, w)
        case Household.Commit{l}:
          keep_seat(l, l1, l2, allowed, s, w)

def seated_fit(l1: Household.Request, l2: Household.Request, +allowed: Nat,
  +s: Household.Seated, w: T(hinv_l(allowed, s, l1, l2)))
  -> T(Nat.is_le(Household.count(s), allowed)):
  match l1:
    case Household.Idle{}:
      match l2:
        case Household.Idle{}:
          w
        case Household.Adds{who}:
          T.and_fst(Nat.is_le(Household.count(s), allowed),
            Nat.is_le(Household.count(Household.seat(who, s)), allowed), w)
    case Household.Adds{who}:
      match l2:
        case Household.Idle{}:
          T.and_fst(Nat.is_le(Household.count(s), allowed),
            Nat.is_le(Household.count(Household.seat(who, s)), allowed), w)
        case Household.Adds{other}:
          match w:

def not_gt(c: Cmp, w: T(Cmp.is_le(c))) -> {Cmp.is_gt(c) == False{} : Bool}:
  match c:
    case LT{}:
      {==}
    case EQ{}:
      {==}
    case GT{}:
      match w:

def keep_all_h(ops: List<Household.Op>, +allowed: Nat,
  +h: Household.Household, w: T(hinv(allowed, h)))
  -> {Household.over_allowance(allowed, Household.replay(ops, allowed, h))
    == False{} : Bool}:
  match ops:
    case Nil{}:
      match h:
        case Household.Household{+s, l1, l2}:
          not_gt(Nat.cmp(Household.count(s), allowed),
            seated_fit(l1, l2, allowed, s, w))
    case Con{+e, rest}:
      keep_all_h(rest, allowed, Household.step(allowed, h, e),
        keep_h(allowed, h, e, w))

def Laws.allowance_never_overspent(allowed, ops):
  keep_all_h(ops, allowed, Household.start(), le_zero(allowed))

def Laws.allowance_seats_serial_second():
  {==}
