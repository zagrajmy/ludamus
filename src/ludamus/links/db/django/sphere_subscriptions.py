"""Sphere subscriptions, and the sweep that announces newly published events.

A sphere publishes an event by setting `publication_time`; nothing fires when
that moment arrives. The sweep is that missing edge: it finds events whose
publication time has passed and whose subscribers have not been told, then
stamps `subscribers_announced_at` so each event goes out once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.links.db.django.models import Event, Sphere, SphereSubscription
from ludamus.pacts.dashboard import (
    SphereEventAnnouncementDTO,
    SphereSubscriptionRepositoryProtocol,
    SubscriptionRecipientDTO,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.multiverse import SphereVisibility

if TYPE_CHECKING:
    from datetime import datetime


class SphereSubscriptionRepository(SphereSubscriptionRepositoryProtocol):
    @staticmethod
    def subscribe(*, sphere_id: int, user_id: int) -> None:
        # The id comes off a URL, so it is checked before it reaches a write.
        # The root sphere is nobody's subscription: it is the page's own home
        # and everyone signed in already sees it. A private sphere's news is
        # for its members, who see it in its panel.
        if (
            not Sphere.objects.filter(pk=sphere_id)
            .exclude(site_id=settings.SITE_ID)
            .exclude(visibility=SphereVisibility.PRIVATE)
            .exists()
        ):
            raise NotFoundError
        SphereSubscription.objects.get_or_create(sphere_id=sphere_id, user_id=user_id)

    @staticmethod
    def unsubscribe(*, sphere_id: int, user_id: int) -> None:
        SphereSubscription.objects.filter(sphere_id=sphere_id, user_id=user_id).delete()

    @staticmethod
    def list_pending_announcements(
        *, now: datetime
    ) -> list[SphereEventAnnouncementDTO]:
        """List the published events whose subscribers have not heard yet.

        Returns:
            One entry per event, carrying every subscriber of its sphere.
            Events whose sphere has no subscribers are included, so the sweep
            still stamps them and never revisits them.
        """
        events = list(
            Event.objects.filter(
                publication_time__isnull=False,
                publication_time__lte=now,
                subscribers_announced_at__isnull=True,
                end_time__gte=now,
            )
            .exclude(sphere__visibility=SphereVisibility.PRIVATE)
            .select_related("sphere__site")
            .order_by("publication_time")
        )
        subscribers: dict[int, list[SubscriptionRecipientDTO]] = {}
        for sphere_id, user_id, email in SphereSubscription.objects.filter(
            sphere_id__in={event.sphere_id for event in events}
        ).values_list("sphere_id", "user_id", "user__email"):
            subscribers.setdefault(sphere_id, []).append(
                SubscriptionRecipientDTO(user_id=user_id, email=email)
            )
        return [
            SphereEventAnnouncementDTO(
                event_pk=event.pk,
                event_name=event.name,
                event_slug=event.slug,
                sphere_name=event.sphere.name,
                sphere_domain=event.sphere.site.domain,
                recipients=subscribers.get(event.sphere_id, []),
            )
            for event in events
        ]

    @staticmethod
    def mark_announced(event_pk: int, *, at: datetime) -> None:
        Event.objects.filter(pk=event_pk).update(subscribers_announced_at=at)
