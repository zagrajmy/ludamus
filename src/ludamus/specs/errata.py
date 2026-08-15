"""Business invariants for post-publication agenda changes."""

from datetime import timedelta

# Moving a session logs an unassign and an assign inside one transaction, so
# two rows a blink apart are one move -- and one announcement.
ERRATUM_MOVE_WINDOW = timedelta(seconds=5)
