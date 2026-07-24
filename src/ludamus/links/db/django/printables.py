"""Repository for the pre-event printables reminder sweep.

Finds events starting within the reminder lead time whose organizers have not
printed yet and have not already been reminded, and stamps the two tracking
timestamps on `Event`. URL composition stays in the notifier; this repo only
reports the slug and sphere domain it needs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.links.db.django.models import Event
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
        events = (
            Event.objects.filter(
                start_time__gt=now,
                start_time__lte=now + lead_time,
                printables_last_printed_at__isnull=True,
                printables_reminder_sent_at__isnull=True,
            )
            .select_related("sphere__site")
            .prefetch_related("sphere__managers")
        )
        reminders: list[PrintablesReminderDTO] = []
        for event in events:
            recipients = [
                PrintablesReminderRecipientDTO(user_id=manager.pk, email=manager.email)
                for manager in event.sphere.managers.all()
                if manager.email
            ]
            if not recipients:
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
