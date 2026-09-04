"""Service builders shared by the two composition roots.

`Services` (request-scoped) and `inits.dbos_scheduler` (workflow steps) build
the same services; sharing the wiring here keeps the two copies from drifting.
The offer-expiry scheduler is a parameter so this module imports neither of
its consumers (which is also what keeps it cycle-free).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.conf import settings

from ludamus.inits.repositories import Repositories
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.links.encryption import FernetDecryptor
from ludamus.links.google_sheets import GoogleSheetsWriter
from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.mills.konwencik import KonwencikExportService
from ludamus.mills.printing import PrintablesReminderService
from ludamus.pacts.konwencik import KonwencikScheduleRepos

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


def build_konwencik_export() -> KonwencikExportService:
    repos = Repositories()
    key: str = settings.CREDENTIALS_ENCRYPTION_KEY
    return KonwencikExportService(
        repos=KonwencikScheduleRepos(
            agenda_items=repos.agenda_items,
            spaces=repos.spaces,
            tracks=repos.tracks,
            sessions=repos.sessions,
            session_fields=repos.session_fields,
            events=repos.events,
            categories=repos.proposal_categories,
        ),
        integrations=repos.event_integrations,
        connections=repos.connections,
        decryptor=FernetDecryptor(key),
        sheet_writer=GoogleSheetsWriter(),
        zone=ZoneInfo(settings.TIME_ZONE),
        transaction=DjangoTransaction(),
    )
