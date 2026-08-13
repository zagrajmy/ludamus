from django.db.models import Exists, OuterRef, QuerySet

from ludamus.links.db.django.models import Session, Track


def hide_private_track_sessions(queryset: QuerySet[Session]) -> QuerySet[Session]:
    # A session without tracks is public (events that don't use tracks at all);
    # one with tracks needs at least one public track. Exists() rather than
    # Count("tracks"): a third aggregate over a m2m fans out the joins and
    # inflates the participation counts annotated alongside.
    return queryset.filter(
        Exists(Track.objects.filter(sessions=OuterRef("pk"), is_public=True))
        | ~Exists(Track.objects.filter(sessions=OuterRef("pk"), is_public=False))
    )


def public_scheduled_sessions(event_id: int | OuterRef) -> QuerySet[Session]:
    return hide_private_track_sessions(
        Session.objects.filter(event_id=event_id, agenda_item__isnull=False)
    )
