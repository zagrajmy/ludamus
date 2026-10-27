# FINDING: a double-submitted accept answers with a 500.
#
# The accept form is submitted twice (a double click, a retry). Both requests
# pass _load's PENDING check before either commits; the second create hits the
# one-to-one AgendaItem.session and raises IntegrityError, which the view does
# not catch.
#
# This file checks while the bug is there. Once the code and room.bend recheck
# the status inside the transaction, the witness stops computing to True:
# delete this file and state the law in LAWS.bend.

import Base
import ./room.bend as Room

law double_submit_crashes:
  exs ops: List<Room.Op>
  {Room.crashed(Room.replay(ops, Room.start())) == True{} : Bool}

def double_submit_crashes():
  ops = {[Room.Accept{Room.L1{}, Room.P{}}, Room.Accept{Room.L2{}, Room.P{}},
    Room.Commit{Room.L1{}}, Room.Commit{Room.L2{}}] : List<Room.Op>}
  (ops, {==})
