"""In-system scheduler backed by DBOS: durable timers plus cron workflows.

Owns the process-wide DBOS instance (checkpointed in
``DBOS_SYSTEM_DATABASE_URL``, isolated from the application tables). Two kinds
of work live here:

- a durable per-offer timer for offer-and-claim: a checkpointed workflow sleeps
  until the offer deadline and then runs ``WaitlistPromotionService
  .expire_offer`` (behind ``OfferExpirySchedulerProtocol`` so it is swappable
  with the cron sweep);
- ``@DBOS.scheduled`` cron workflows for the periodic sweeps, so they run
  in-process without external cron. Each tick fires once across all gunicorn
  workers (DBOS dedups on schedule name + tick in the system database).

The per-offer timers and the offers sweep intentionally coexist. The timer
hands a freed seat to the next waiting party at the exact deadline — during a
live event a popular session's seat should not idle for minutes — while the
sweep is the recovery floor for timers that were never armed (the timer is
started after commit, so a crash in between loses it) or that belonged to a
process that never came back (open-source DBOS recovers a process's own
pending workflows, not a dead peer's). Claim *correctness* depends on neither:
``claim_offer`` re-checks ``offer_expires_at`` itself.

``ServiceInjectionMiddleware`` calls ``launch_scheduler`` when a serving
process builds its handler; construction and launch stay lazy so importing
this module (or running the rest of the suite) never starts DBOS.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from dbos import DBOS
from django.conf import settings

from ludamus.inits.builders import build_printables_reminder, build_waitlist_promotion

logger = logging.getLogger(__name__)

_launched = threading.Event()
_launch_lock = threading.Lock()

# Cron cadences (croniter syntax). The offers sweep is the recovery floor
# under the per-offer timers (see the module docstring); printables reminders
# go out each morning, Polish time being UTC+1/+2.
EXPIRE_OFFERS_SCHEDULE = "*/5 * * * *"
PRINTABLES_REMINDERS_SCHEDULE = "0 7 * * *"


@DBOS.step()
def _expire_offer_step(participation_id: int) -> None:
    # Re-offers produced by the expiry stay durable by reusing this scheduler.
    build_waitlist_promotion(DBOSOfferExpiryScheduler()).expire_offer(
        participation_id=participation_id
    )


@DBOS.workflow()
def _expire_offer_workflow(participation_id: int, delay_seconds: float) -> None:
    DBOS.sleep(delay_seconds)
    _expire_offer_step(participation_id)


@DBOS.step()
def _expire_lapsed_offers_step(now: datetime) -> None:
    service = build_waitlist_promotion(DBOSOfferExpiryScheduler())
    expired = service.expire_lapsed_offers(now=now)
    logger.info("expire_offers sweep: processed %s lapsed offer(s)", expired)


@DBOS.scheduled(EXPIRE_OFFERS_SCHEDULE)
@DBOS.workflow()
def expire_offers_sweep(scheduled: datetime, _actual: datetime) -> None:
    _expire_lapsed_offers_step(scheduled)


@DBOS.step()
def _send_printables_reminders_step(now: datetime) -> None:
    reminded = build_printables_reminder().send_due_reminders(now=now)
    logger.info("printables reminders: reminded %s event(s)", reminded)


@DBOS.scheduled(PRINTABLES_REMINDERS_SCHEDULE)
@DBOS.workflow()
def printables_reminders_tick(scheduled: datetime, _actual: datetime) -> None:
    _send_printables_reminders_step(scheduled)


def _ensure_launched() -> None:
    if _launched.is_set():
        return
    with _launch_lock:  # double-checked so concurrent requests launch DBOS once
        if _launched.is_set():
            return
        DBOS(
            config={
                "name": "ludamus",
                "system_database_url": settings.DBOS_SYSTEM_DATABASE_URL,
                "run_admin_server": False,
            }
        )
        DBOS.launch()
        _launched.set()
        logger.info(
            "DBOS launched; schedules active: %s",
            [w.__name__ for w in (expire_offers_sweep, printables_reminders_tick)],
        )


def launch_scheduler() -> None:
    # Called when a serving process builds its handler (per gunicorn worker,
    # post-fork) so the cron workflows run without waiting for traffic. Launch
    # runs on a daemon thread: it does IO (system-schema migration), and a
    # failure there must not take request serving down — the thread dies loudly
    # via threading.excepthook while the management commands remain the manual
    # floor. The next schedule_expiry call retries the launch.
    if settings.SCHEDULER_MODE != "dbos":
        return
    threading.Thread(target=_ensure_launched, name="dbos-launch", daemon=True).start()


class DBOSOfferExpiryScheduler:
    @staticmethod
    def schedule_expiry(*, participation_id: int, run_at: datetime) -> None:
        _ensure_launched()
        delay = max(0.0, (run_at - datetime.now(UTC)).total_seconds())
        DBOS.start_workflow(_expire_offer_workflow, participation_id, delay)
