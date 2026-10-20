# The laws. PROOF.bend proves each one; `bend PROOF.bend` is the gate.

import Base
import ./seats.bend as Seats
import ./schedule.bend as Schedule

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
