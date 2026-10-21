# The laws. PROOF.bend proves each one; `bend PROOF.bend` is the gate.

import Base
import ./sends.bend as Sends

# LAW: one sweep at a time, an event is announced once: the second sweep finds
# it stamped and leaves it.
law serial_sweeps_announce_once:
  ops = {[Sends.Scan{Sends.R1{}}, Sends.Send{Sends.R1{}},
    Sends.Scan{Sends.R2{}}, Sends.Send{Sends.R2{}}] : List<Sends.Op>}
  {Sends.sent_twice(Sends.replay(ops, Sends.start())) == False{} : Bool}
