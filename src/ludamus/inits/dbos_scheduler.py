"""In-system scheduler backed by DBOS: durable timers plus cron workflows.

Owns the process-wide DBOS instance (checkpointed in
``DBOS_SYSTEM_DATABASE_URL``, isolated from the application tables). Two kinds
of work live here:

- a durable per-offer timer for offer-and-claim: a checkpointed workflow sleeps
  until the offer deadline and then runs ``WaitlistPromotionService
  .expire_offer``, surviving restarts (behind ``OfferExpirySchedulerProtocol``
  so it is swappable with the cron sweep);
- ``@DBOS.scheduled`` cron workflows for the periodic sweeps, so they run
  in-process without external cron. Each tick fires once across all gunicorn
  workers (DBOS dedups on schedule name + tick in the system database).

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

from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.mills.printing import PrintablesReminderService

logger = logging.getLogger(__name__)

_launched = threading.Event()
_launch_lock = threading.Lock()

# Cron cadences (croniter syntax). The offers sweep is the belt-and-suspenders
# floor under the per-offer timers (it catches timers lost to a crash);
# printables reminders go out each morning, Polish time being UTC+1/+2.
EXPIRE_OFFERS_SCHEDULE = "*/5 * * * *"
PRINTABLES_REMINDERS_SCHEDULE = "0 7 * * *"


def _build_service() -> WaitlistPromotionService:
    # Built locally (not via inits.services) to keep this module free of the
    # composition root and avoid an import cycle. Re-offers stay durable by
    # reusing the DBOS scheduler.
    return WaitlistPromotionService(
        DjangoTransaction(),
        Repositories().participation_promotion,
        DjangoUserNotifier(),
        DBOSOfferExpiryScheduler(),
    )


def _build_printables_service() -> PrintablesReminderService:
    return PrintablesReminderService(
        transaction=DjangoTransaction(),
        reminders=Repositories().printables_reminders,
        notifier=DjangoUserNotifier(),
    )


@DBOS.step()
def _expire_offer_step(participation_id: int) -> None:
    _build_service().expire_offer(participation_id=participation_id)


@DBOS.workflow()
def _expire_offer_workflow(participation_id: int, delay_seconds: float) -> None:
    DBOS.sleep(delay_seconds)
    _expire_offer_step(participation_id)


@DBOS.step()
def _expire_lapsed_offers_step(now: datetime) -> None:
    expired = _build_service().expire_lapsed_offers(now=now)
    logger.info("expire_offers sweep: processed %s lapsed offer(s)", expired)


@DBOS.scheduled(EXPIRE_OFFERS_SCHEDULE)
@DBOS.workflow()
def expire_offers_sweep(scheduled: datetime, _actual: datetime) -> None:
    _expire_lapsed_offers_step(scheduled)


@DBOS.step()
def _send_printables_reminders_step(now: datetime) -> None:
    reminded = _build_printables_service().send_due_reminders(now=now)
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
    if settings.OFFER_EXPIRY_SCHEDULER != "dbos":
        return
    threading.Thread(target=_ensure_launched, name="dbos-launch", daemon=True).start()


class DBOSOfferExpiryScheduler:
    @staticmethod
    def schedule_expiry(*, participation_id: int, run_at: datetime) -> None:
        _ensure_launched()
        delay = max(0.0, (run_at - datetime.now(UTC)).total_seconds())
        DBOS.start_workflow(_expire_offer_workflow, participation_id, delay)
