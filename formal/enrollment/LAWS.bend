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

# LAW: whatever happens to one person's rows in two overlapping sessions, in
# any order and any number of times, with requests interleaved however they
# can be, the person never ends CONFIRMED in both.
law no_double_booking:
  for ops: List<Schedule.Op>
  {Schedule.double_booked(Schedule.replay(ops, Schedule.start())) == False{}
    : Bool}

# LAW: one request at a time, an enroll into A seats the person. With
# conflict_blocks_serial_enroll this pins the conflict check from both sides.
law enroll_seats_serial_first:
  ops = {[Schedule.Enroll{Schedule.A{}}, Schedule.Commit{Schedule.A{}}]
    : List<Schedule.Op>}
  person = Schedule.replay(ops, Schedule.start())
  {Schedule.is_confirmed(Schedule.row(Schedule.A{}, person)) == True{} : Bool}

# LAW: one request at a time, a confirmed seat in A blocks an enroll in B.
# This pins the model's conflict check to the code's.
law conflict_blocks_serial_enroll:
  ops = {[Schedule.Enroll{Schedule.A{}}, Schedule.Commit{Schedule.A{}},
    Schedule.Enroll{Schedule.B{}}, Schedule.Commit{Schedule.B{}}] : List<Schedule.Op>}
  person = Schedule.replay(ops, Schedule.start())
  {Schedule.double_booked(person) == False{} : Bool}

# LAW: whatever requests spend one owner's passes, interleaved however they
# can be, they never seat more distinct people than the owner holds passes.
law allowance_never_overspent:
  for +allowed: Nat
  for ops: List<Household.Op>
  house = Household.replay(ops, allowed, Household.start())
  {Household.over_allowance(allowed, house) == False{} : Bool}

# LAW: one request at a time, an owner with 2 passes cannot seat a third
# person. This pins the model's allowance check to can_enroll_users.
law allowance_refuses_serial_third:
  ops = {[Household.Check{Household.L1{}, Household.Owner{}},
    Household.Commit{Household.L1{}},
    Household.Check{Household.L1{}, Household.First{}},
    Household.Commit{Household.L1{}},
    Household.Check{Household.L1{}, Household.Second{}},
    Household.Commit{Household.L1{}}] : List<Household.Op>}
  house = Household.replay(ops, 2n, Household.start())
  {Household.over_allowance(2n, house) == False{} : Bool}

# LAW: one request at a time, an owner with 2 passes seats a second person.
# With allowance_refuses_serial_third this pins the check from both sides, so
# allowance_never_overspent cannot hold just because the model refuses all.
law allowance_seats_serial_second:
  ops = {[Household.Check{Household.L1{}, Household.Owner{}},
    Household.Commit{Household.L1{}},
    Household.Check{Household.L2{}, Household.First{}},
    Household.Commit{Household.L2{}}] : List<Household.Op>}
  house = Household.replay(ops, 2n, Household.start())
  {Household.count(Household.seated(house)) == 2n : Nat}
