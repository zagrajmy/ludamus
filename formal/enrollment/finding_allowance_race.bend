# FINDING: two requests at once seat more people than the owner has passes.
#
# The owner holds 2 passes and is seated. Request 1 enrolls companion First
# into one session while request 2 enrolls companion Second into another. Each
# runs can_enroll_users before the other commits and reads {owner}, so each
# sees 2 <= 2. They lock different Session rows, and both commit: 3 people on
# 2 passes. fill_freed_seats reads owner_slots_remaining under its own session
# lock only, so a promotion can race an enroll the same way.
#
# This file checks while the bug is there. Once the code and allowance.bend
# serialise the allowance check, the witness stops computing to True: delete
# this file and state the law in LAWS.bend.

import Base
import ./allowance.bend as H

law allowance_race_overspends:
  exs ops: List<H.Op>
  {H.over_allowance(2n, H.replay(ops, 2n, H.start())) == True{} : Bool}

def allowance_race_overspends():
  ops = {[H.Check{H.L1{}, H.Owner{}}, H.Commit{H.L1{}},
    H.Check{H.L1{}, H.First{}}, H.Check{H.L2{}, H.Second{}},
    H.Commit{H.L1{}}, H.Commit{H.L2{}}] : List<H.Op>}
  (ops, {==})
