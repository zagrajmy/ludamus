# FINDING: a held or offered seat gets past the conflict check.
#
# A leader holds a seat for P in A (hold_seat), or the waiting list offers P a
# seat in A (OFFER_CLAIM). P enrolls in B, which overlaps A: conflicted_user_ids
# counts only CONFIRMED rows, so the OFFERED row in A does not count. P then
# claims A, and _claim -> mark_claimed never rechecks. P is CONFIRMED in both.
# No race is needed; this one was reproduced against the real views.
#
# This file checks while the bug is there. Once the code and schedule.bend
# close the gap, the witness below stops computing to True: delete this file
# and state the law in LAWS.bend.

import Base
import ./schedule.bend as S

law offered_seat_double_books:
  exs ops: List<S.Op>
  {S.double_booked(S.replay(ops, S.start())) == True{} : Bool}

def offered_seat_double_books():
  ops = {[S.Hold{S.A{}}, S.Commit{S.A{}}, S.Enroll{S.B{}}, S.Commit{S.B{}},
    S.Claim{S.A{}}] : List<S.Op>}
  (ops, {==})
