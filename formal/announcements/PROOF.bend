# The proofs of LAWS.bend: each law is about one concrete run, so Bend checks
# it by computing the run.

import Base
import ./sends.bend as Sends
import ./LAWS.bend as Laws

def Laws.serial_sweeps_announce_once():
  {==}
