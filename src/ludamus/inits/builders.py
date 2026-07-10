"""Service builders shared by the two composition roots.

`Services` (request-scoped) and `inits.dbos_scheduler` (workflow steps) build
the same services; sharing the wiring here keeps the two copies from drifting.
The offer-expiry scheduler is a parameter so this module imports neither of
its consumers (which is also what keeps it cycle-free).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.mills.printing import PrintablesReminderService

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import OfferExpirySchedulerProtocol


def build_waitlist_promotion(
    scheduler: OfferExpirySchedulerProtocol,
) -> WaitlistPromotionService:
    return WaitlistPromotionService(
        DjangoTransaction(),
        Repositories().participation_promotion,
        DjangoUserNotifier(),
        scheduler,
    )


def build_printables_reminder() -> PrintablesReminderService:
    return PrintablesReminderService(
        transaction=DjangoTransaction(),
        reminders=Repositories().printables_reminders,
        notifier=DjangoUserNotifier(),
    )
