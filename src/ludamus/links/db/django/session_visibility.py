from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import Session

if TYPE_CHECKING:
    from django.db.models import OuterRef, QuerySet


def public_scheduled_sessions(event_id: int | OuterRef) -> QuerySet[Session]:
    return Session.objects.filter(event_id=event_id, agenda_item__isnull=False).exclude(
        tracks__is_public=False
    )


def is_publicly_scheduled(*, event_id: int, session_id: int) -> bool:
    return public_scheduled_sessions(event_id).filter(pk=session_id).exists()
