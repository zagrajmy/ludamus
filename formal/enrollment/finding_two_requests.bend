# FINDING: two requests at once double-book a person.
#
# P sends an enroll for A and an enroll for B, which overlap. Each request
# locks only its own Session row, and each runs has_conflicts before the other
# commits, so neither sees a conflict. Both commit: P is CONFIRMED in A and B.
# fill_freed_seats has the same shape, so a promotion can race an enroll too.
#
# This file checks while the bug is there. Once the code and schedule.bend
# serialise the two checks, the witness below stops computing to True: delete
# this file and state the law in LAWS.bend.

import Base
import ./schedule.bend as S

law two_requests_double_book:
  exs ops: List<S.Op>
  {S.double_booked(S.replay(ops, S.start())) == True{} : Bool}

def two_requests_double_book():
  ops = {[S.Enroll{S.A{}}, S.Enroll{S.B{}}, S.Commit{S.A{}}, S.Commit{S.B{}}]
    : List<S.Op>}
  (ops, {==})
