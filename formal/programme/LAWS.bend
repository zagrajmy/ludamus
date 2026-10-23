# The laws. PROOF.bend proves each one; `bend PROOF.bend` is the gate.

import Base
import ./room.bend as Room

# LAW: one accept at a time, a space and slot holds one proposal: the second
# accept sees the first one's agenda item and is refused.
law serial_accepts_never_share_a_slot:
  ops = {[Room.Accept{Room.L1{}, Room.P{}}, Room.Commit{Room.L1{}},
    Room.Accept{Room.L1{}, Room.Q{}}, Room.Commit{Room.L1{}}] : List<Room.Op>}
  {Room.double_booked(Room.replay(ops, Room.start())) == False{} : Bool}

# LAW: accepting a proposal again once it is placed is refused, not a 500.
law serial_reaccept_is_refused:
  ops = {[Room.Accept{Room.L1{}, Room.P{}}, Room.Commit{Room.L1{}},
    Room.Accept{Room.L1{}, Room.P{}}, Room.Commit{Room.L1{}}] : List<Room.Op>}
  {Room.crashed(Room.replay(ops, Room.start())) == False{} : Bool}
