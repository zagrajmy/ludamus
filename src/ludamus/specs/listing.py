"""Business invariants for board listings."""

from datetime import timedelta

# An open listing nobody closed is stale after this long; reopening restarts it.
LISTING_OPEN_FOR = timedelta(days=30)
