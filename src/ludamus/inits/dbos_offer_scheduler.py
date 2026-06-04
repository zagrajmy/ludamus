"""Durable offer-expiry scheduler backed by DBOS.

Opt-in (``OFFER_EXPIRY_SCHEDULER=dbos``) durable timer for offer-and-claim: a
checkpointed workflow sleeps until the offer deadline and then runs
``WaitlistPromotionService.expire_offer``, surviving restarts. Sits behind
``OfferExpirySchedulerProtocol`` so it is swappable with the cron sweep.

DBOS keeps its own system database (``DBOS_SYSTEM_DATABASE_URL``), isolated from
the application DB. Construction and launch are lazy so importing this module
(or running the rest of the suite) never starts DBOS.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from dbos import DBOS
from django.conf import settings

from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.mills.enrollment import WaitlistPromotionService

_launched = threading.Event()
_launch_lock = threading.Lock()


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


@DBOS.step()
def _expire_offer_step(participation_id: int) -> None:
    _build_service().expire_offer(participation_id=participation_id)


@DBOS.workflow()
def _expire_offer_workflow(participation_id: int, delay_seconds: float) -> None:
    DBOS.sleep(delay_seconds)
    _expire_offer_step(participation_id)


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


class DBOSOfferExpiryScheduler:
    @staticmethod
    def schedule_expiry(*, participation_id: int, run_at: datetime) -> None:
        _ensure_launched()
        delay = max(0.0, (run_at - datetime.now(UTC)).total_seconds())
        DBOS.start_workflow(_expire_offer_workflow, participation_id, delay)
