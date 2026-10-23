"""Sphere subscriptions, and the sweep that announces newly published events.

A sphere publishes an event by setting `publication_time`; nothing fires when
that moment arrives. The sweep is that missing edge: it finds events whose
publication time has passed and whose subscribers have not been told, then
stamps `subscribers_announced_at` so each event goes out once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.links.db.django.event_visibility import listed_events
from ludamus.links.db.django.models import Event, Sphere, SphereSubscription, User
from ludamus.pacts.crowd import AgeBand
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
    def lock_subscriber_age_band(user_id: int) -> AgeBand:
        return AgeBand(
            User.objects.select_for_update()
            .values_list("age_band", flat=True)
            .get(pk=user_id)
        )

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
    def unsubscribe_everywhere(user_id: int) -> None:
        SphereSubscription.objects.filter(user_id=user_id).delete()

    @staticmethod
    def list_recipients(sphere_id: int) -> list[SubscriptionRecipientDTO]:
        return [
            SubscriptionRecipientDTO(
                user_id=user_id, email=email, age_band=AgeBand(age_band)
            )
            for user_id, email, age_band in SphereSubscription.objects.filter(
                sphere_id=sphere_id
            ).values_list("user_id", "user__email", "user__age_band")
        ]

    @staticmethod
    def list_pending_announcements(
        *, now: datetime
    ) -> list[SphereEventAnnouncementDTO]:
        """List the published events whose subscribers have not heard yet.

        Returns:
            One entry per event, whether or not its sphere has subscribers, so
            the sweep still stamps each one and never revisits it.
        """
        events = list(
            Event.objects.filter(
                listed_events(now=now),
                subscribers_announced_at__isnull=True,
                end_time__gte=now,
            )
            .exclude(sphere__visibility=SphereVisibility.PRIVATE)
            .select_related("sphere__site")
            .order_by("publication_time")
        )
        return [
            SphereEventAnnouncementDTO(
                event_pk=event.pk,
                event_name=event.name,
                event_slug=event.slug,
                sphere_id=event.sphere_id,
                sphere_name=event.sphere.name,
                sphere_domain=event.sphere.site.domain,
            )
            for event in events
        ]

    @staticmethod
    def mark_announced(event_pk: int, *, at: datetime) -> None:
        Event.objects.filter(pk=event_pk).update(subscribers_announced_at=at)
