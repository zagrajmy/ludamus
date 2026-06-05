"""Coverage for the DBOS offer-expiry scheduler adapter.

Launches a real DBOS instance (isolated SQLite system DB) and drives the
opt-in scheduler end to end: schedule_expiry → durable workflow → step →
expire_offer. Uses a non-existent participation so the workflow is a safe
no-op; the point is that every line of the adapter executes on 3.14.
"""

import threading
import time
from datetime import UTC, datetime

import pytest
from dbos import DBOS

from ludamus.inits import dbos_offer_scheduler as scheduler_module

_MISSING_PARTICIPATION_ID = 10_000_000


@pytest.mark.django_db(transaction=True)
def test_dbos_scheduler_runs_expiry_workflow(settings, tmp_path, monkeypatch):
    settings.DBOS_SYSTEM_DATABASE_URL = f"sqlite:///{tmp_path / 'dbos_sys.sqlite'}"
    # Fresh launch flag so _ensure_launched runs against this test's system DB.
    monkeypatch.setattr(scheduler_module, "_launched", threading.Event())

    try:
        scheduler_module.DBOSOfferExpiryScheduler().schedule_expiry(
            participation_id=_MISSING_PARTICIPATION_ID, run_at=datetime.now(UTC)
        )
        # Let the durable workflow (zero delay) run its step before teardown.
        time.sleep(2)
    finally:
        DBOS.destroy()
