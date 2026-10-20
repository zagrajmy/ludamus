# The laws. PROOF.bend proves each one; `bend PROOF.bend` is the gate.

import Base
import ./seats.bend as Seats
import ./schedule.bend as Schedule
import ./allowance.bend as Household

# LAW: whatever happens to a session's seats, in any order and any number of
# times, it never seats more people than its participants_limit.
law capacity:
  for +limit: Nat
  for ops: List<Seats.Op>
  seats = Seats.replay(ops, limit, Seats.start())
  {Nat.is_le(Seats.taken(seats), limit) == True{} : Bool}

# LAW: one request at a time, a confirmed seat in A blocks an enroll in B.
# This pins the model's conflict check to the code's; the ways around it are
# in the finding_*.bend files.
law conflict_blocks_serial_enroll:
  ops = {[Schedule.Enroll{Schedule.A{}}, Schedule.Commit{Schedule.A{}},
    Schedule.Enroll{Schedule.B{}}, Schedule.Commit{Schedule.B{}}] : List<Schedule.Op>}
  person = Schedule.replay(ops, Schedule.start())
  {Schedule.double_booked(person) == False{} : Bool}

# LAW: one request at a time, an owner with 2 passes cannot seat a third
# person. This pins the model's allowance check to can_enroll_users; the race
# around it is finding_allowance_race.bend.
law allowance_refuses_serial_third:
  ops = {[Household.Check{Household.L1{}, Household.Owner{}},
    Household.Commit{Household.L1{}},
    Household.Check{Household.L1{}, Household.First{}},
    Household.Commit{Household.L1{}},
    Household.Check{Household.L1{}, Household.Second{}},
    Household.Commit{Household.L1{}}] : List<Household.Op>}
  house = Household.replay(ops, 2n, Household.start())
  {Household.over_allowance(2n, house) == False{} : Bool}
