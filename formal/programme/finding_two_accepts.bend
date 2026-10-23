# FINDING: two accepts at once put two proposals in one space and slot.
#
# Two managers accept P and Q into the same space and time slot. Each runs
# list_overlapping_in_space before the other commits, sees nothing, and creates
# its AgendaItem: the timetable now holds two programme items in one room at
# once. assign_session locks the space but never checks for overlap, so the two
# placement paths disagree on what keeps a room single-booked.
#
# This file checks while the bug is there. Once the code and room.bend
# serialise the overlap check, the witness stops computing to True: delete
# this file and state the law in LAWS.bend.

import Base
import ./room.bend as Room

law two_accepts_share_a_slot:
  exs ops: List<Room.Op>
  {Room.double_booked(Room.replay(ops, Room.start())) == True{} : Bool}

def two_accepts_share_a_slot():
  ops = {[Room.Accept{Room.L1{}, Room.P{}}, Room.Accept{Room.L2{}, Room.Q{}},
    Room.Commit{Room.L1{}}, Room.Commit{Room.L2{}}] : List<Room.Op>}
  (ops, {==})
