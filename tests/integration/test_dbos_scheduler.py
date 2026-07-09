"""Coverage for the DBOS in-system scheduler.

Launches a real DBOS instance (isolated SQLite system DB) and drives the
adapter end to end: schedule_expiry → durable workflow → step → expire_offer,
plus the cron workflows run as plain workflows (their crons are trusted to
DBOS; what we own is the step wiring underneath). Uses a non-existent
participation / an empty events table so the workflows are safe no-ops; the
point is that every line of the adapter executes on 3.14.
"""

import threading
import time
from datetime import UTC, datetime

import pytest
from dbos import DBOS

from ludamus.inits import dbos_scheduler as scheduler_module

_MISSING_PARTICIPATION_ID = 10_000_000
# The scheduled workflow has zero delay; this is slack for the DBOS worker
# thread to pick it up and run its step before teardown destroys DBOS.
_WORKFLOW_GRACE_SECONDS = 2.0
_LAUNCH_TIMEOUT_SECONDS = 30.0


@pytest.mark.django_db(transaction=True)
def test_dbos_scheduler_runs_expiry_workflow(settings, tmp_path, monkeypatch):
    settings.DBOS_SYSTEM_DATABASE_URL = f"sqlite:///{tmp_path / 'dbos_sys.sqlite'}"
    # Fresh launch flag (kept as a local handle so we can assert on it without
    # reaching into module privates) so _ensure_launched runs for this test.
    launched = threading.Event()
    monkeypatch.setattr(scheduler_module, "_launched", launched)

    scheduler = scheduler_module.DBOSOfferExpiryScheduler()
    try:
        scheduler.schedule_expiry(
            participation_id=_MISSING_PARTICIPATION_ID, run_at=datetime.now(UTC)
        )
        # _ensure_launched constructed and launched DBOS.
        assert launched.is_set()
        # A second schedule short-circuits launch on the already-set flag.
        scheduler.schedule_expiry(
            participation_id=_MISSING_PARTICIPATION_ID, run_at=datetime.now(UTC)
        )
        # Let the durable workflows (zero delay) run their steps before teardown.
        time.sleep(_WORKFLOW_GRACE_SECONDS)
    finally:
        DBOS.destroy()


@pytest.mark.django_db(transaction=True)
def test_cron_workflows_execute_their_sweeps(settings, tmp_path, monkeypatch):
    settings.DBOS_SYSTEM_DATABASE_URL = f"sqlite:///{tmp_path / 'dbos_sys.sqlite'}"
    settings.OFFER_EXPIRY_SCHEDULER = "dbos"
    launched = threading.Event()
    monkeypatch.setattr(scheduler_module, "_launched", launched)

    # launch_scheduler starts the launch on a background thread (fail-soft).
    scheduler_module.launch_scheduler()
    assert launched.wait(timeout=_LAUNCH_TIMEOUT_SECONDS)

    now = datetime.now(UTC)
    try:
        # The cron trigger itself is DBOS's croniter loop; drive the same
        # workflows manually and assert the sweeps complete against the DB.
        DBOS.start_workflow(scheduler_module.expire_offers_sweep, now, now).get_result()
        DBOS.start_workflow(
            scheduler_module.printables_reminders_tick, now, now
        ).get_result()
    finally:
        DBOS.destroy()


def test_launch_scheduler_skips_when_cron(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_module, "_ensure_launched", lambda: calls.append(1))
    settings.OFFER_EXPIRY_SCHEDULER = "cron"

    scheduler_module.launch_scheduler()

    assert not calls


def test_launch_race_loser_rechecks_under_the_lock(settings, monkeypatch):
    # The loser of a concurrent launch must take the double-checked return
    # instead of constructing DBOS a second time.
    settings.OFFER_EXPIRY_SCHEDULER = "dbos"
    constructed = []
    monkeypatch.setattr(
        scheduler_module, "DBOS", lambda *_args, **_kwargs: constructed.append(1)
    )
    launched = threading.Event()
    lock = threading.Lock()
    monkeypatch.setattr(scheduler_module, "_launched", launched)
    monkeypatch.setattr(scheduler_module, "_launch_lock", lock)

    with lock:  # the launch thread blocks here, losing the race
        scheduler_module.launch_scheduler()
        launched.set()  # the "winner" finishes while the loser waits
    for thread in threading.enumerate():
        if thread.name == "dbos-launch":
            thread.join(timeout=10)

    assert not constructed
