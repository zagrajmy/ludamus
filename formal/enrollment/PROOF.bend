# The proof of LAWS.bend.
#
# The argument: the seats taken plus the seats the lock holder has reserved
# never exceed the limit. It holds at the start, and every op keeps it: a check
# reserves only what fits, a commit turns the reservation into taken seats, a
# free only lowers the count, and a check that finds the lock held waits.

import Base
import ./seats.bend as Seats
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
