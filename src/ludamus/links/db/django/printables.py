"""Repository for the pre-event printables reminder sweep.

Finds events starting within the reminder lead time whose organizers have not
printed yet and have not already been reminded, and stamps the two tracking
timestamps on `Event`. URL composition stays in the notifier; this repo only
reports the slug and sphere domain it needs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.links.db.django.models import Event, SphereMembership
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.printing import (
    PrintablesReminderDTO,
    PrintablesReminderRecipientDTO,
    PrintablesReminderRepositoryProtocol,
)

if TYPE_CHECKING:
    from datetime import timedelta


class PrintablesReminderRepository(PrintablesReminderRepositoryProtocol):
    @staticmethod
    def list_pending_reminders(
        *, now: datetime, lead_time: timedelta
    ) -> list[PrintablesReminderDTO]:
        events = list(
            Event.objects.filter(
                start_time__gt=now,
                start_time__lte=now + lead_time,
                printables_last_printed_at__isnull=True,
                printables_reminder_sent_at__isnull=True,
            ).select_related("sphere__site")
        )
        # Printing is a manager's chore; comms members don't get nagged about
        # it. One query for every sphere on the sweep, keyed by sphere.
        recipients_by_sphere: dict[int, list[PrintablesReminderRecipientDTO]] = (
            defaultdict(list)
        )
        for membership in SphereMembership.objects.filter(
            sphere_id__in={event.sphere_id for event in events}, role=SphereRole.MANAGER
        ).select_related("user"):
            if membership.user.email:
                recipients_by_sphere[membership.sphere_id].append(
                    PrintablesReminderRecipientDTO(
                        user_id=membership.user.pk, email=membership.user.email
                    )
                )

        reminders: list[PrintablesReminderDTO] = []
        for event in events:
            if not (recipients := recipients_by_sphere[event.sphere_id]):
                continue
            reminders.append(
                PrintablesReminderDTO(
                    event_pk=event.pk,
                    event_name=event.name,
                    event_slug=event.slug,
                    sphere_domain=event.sphere.site.domain,
                    recipients=recipients,
                )
            )
        return reminders

    @staticmethod
    def mark_printed(event_pk: int) -> None:
        Event.objects.filter(pk=event_pk).update(
            printables_last_printed_at=datetime.now(UTC)
        )

    @staticmethod
    def mark_reminder_sent(event_pk: int, *, at: datetime) -> None:
        Event.objects.filter(pk=event_pk).update(printables_reminder_sent_at=at)
