# FINDING: two overlapping sweeps announce an event twice.
#
# The DBOS tick and the management command both list the event before either
# stamps it. Each then runs its per-event transaction: mark_announced updates
# the row again (nothing filters on the stamp being null), and every subscriber
# is notified twice. send_printables_reminders has the same shape around
# mark_reminder_sent. The announcement fanout in notifications.py already claims
# with `notified_at__isnull`; that is the pattern a fix can copy.
#
# This file checks while the bug is there. Once the code and sends.bend claim
# the stamp, the witness stops computing to True: delete this file and state
# the law in LAWS.bend.

import Base
import ./sends.bend as Sends

law overlapping_sweeps_send_twice:
  exs ops: List<Sends.Op>
  {Sends.sent_twice(Sends.replay(ops, Sends.start())) == True{} : Bool}

def overlapping_sweeps_send_twice():
  ops = {[Sends.Scan{Sends.R1{}}, Sends.Scan{Sends.R2{}},
    Sends.Send{Sends.R1{}}, Sends.Send{Sends.R2{}}] : List<Sends.Op>}
  (ops, {==})
