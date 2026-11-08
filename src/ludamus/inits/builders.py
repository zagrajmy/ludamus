"""Service builders shared by the request scope and the sweeps.

`Services` (request-scoped) and `inits.sweeps` (run by DBOS and by the
management commands) build the same services; sharing the wiring here keeps
the copies from drifting. The offer-expiry scheduler is a parameter so this
module imports neither `inits.dbos_scheduler` nor `inits.services`, both of
which import it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.conf import settings

from ludamus.inits.config import credentials_key
from ludamus.inits.repositories import Repositories
from ludamus.links.db.django.encounter_invites import DjangoEncounterInviteMailer
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.links.email_tokens import DjangoEmailTokenCodec
from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.links.google_sheets import GoogleSheetsWriter
from ludamus.links.unsubscribe_tokens import DjangoSphereUnsubscribeTokenCodec
from ludamus.mills.crowd import EmailVerificationService
from ludamus.mills.dashboard import SphereSubscriptionService
from ludamus.mills.encounter import EncounterService
from ludamus.mills.encounter_calendar import EncounterGuests
from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.mills.konwencik import KonwencikExportService
from ludamus.mills.listing import ListingService
from ludamus.mills.multiverse import SitesService
from ludamus.mills.notifications import AnnouncementFanoutService
from ludamus.mills.printing import PrintablesReminderService
from ludamus.pacts.konwencik import KonwencikScheduleRepos

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import OfferExpirySchedulerProtocol
    from ludamus.pacts.multiverse import SitesServiceProtocol


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


def build_email_verification() -> EmailVerificationService:
    repos = Repositories()
    return EmailVerificationService(
        transaction=DjangoTransaction(),
        users=repos.active_users,
        reminders=repos.verification_reminders,
        tokens=DjangoEmailTokenCodec(),
        notifier=DjangoUserNotifier(),
    )


def build_announcement_fanout() -> AnnouncementFanoutService:
    return AnnouncementFanoutService(
        DjangoTransaction(), Repositories().announcement_fanout
    )


def build_sphere_subscriptions() -> SphereSubscriptionService:
    return SphereSubscriptionService(
        transaction=DjangoTransaction(),
        subscriptions=Repositories().sphere_subscriptions,
        notifier=DjangoUserNotifier(),
        tokens=DjangoSphereUnsubscribeTokenCodec(),
    )


def build_credentials_encryptor() -> FernetEncryptor:
    return FernetEncryptor(credentials_key())


def build_credentials_decryptor() -> FernetDecryptor:
    return FernetDecryptor(credentials_key())


def build_konwencik_export() -> KonwencikExportService:
    repos = Repositories()
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
        decryptor=build_credentials_decryptor(),
        sheet_writer=GoogleSheetsWriter(),
        zone=ZoneInfo(settings.TIME_ZONE),
        transaction=DjangoTransaction(),
    )


def build_sites() -> SitesService:
    repos = Repositories()
    return SitesService(repos.spheres, repos.spheres)


def build_encounter_guests(sites: SitesServiceProtocol) -> EncounterGuests:
    repos = Repositories()
    return EncounterGuests(
        rsvps=repos.encounter_rsvps,
        invitees=repos.encounter_invitees,
        users=repos.active_users,
        sites=sites,
        mailer=DjangoEncounterInviteMailer(),
    )


def build_listings() -> ListingService:
    repos = Repositories()
    return ListingService(
        transaction=DjangoTransaction(),
        listings=repos.listings,
        responses=repos.listing_responses,
        users=repos.active_users,
        tags=repos.tags,
        notifier=DjangoUserNotifier(),
    )


def build_encounters(
    sites: SitesServiceProtocol, guests: EncounterGuests
) -> EncounterService:
    repos = Repositories()
    return EncounterService(
        transaction=DjangoTransaction(),
        encounters=repos.encounters,
        rsvps=repos.encounter_rsvps,
        users=repos.active_users,
        spheres=repos.spheres,
        sites=sites,
        guests=guests,
    )
