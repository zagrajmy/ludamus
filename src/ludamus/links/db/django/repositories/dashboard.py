"""Cross-sphere reads for the signed-in home page.

Every other repository answers within one sphere, because every other page
belongs to one. The dashboard is the exception: it is the root sphere's page
about all of them, so each row carries its own absolute URL and the sphere it
came from.
"""

from __future__ import annotations

from operator import attrgetter
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Count, Q
from django.urls import reverse

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.models import (
    Encounter,
    Event,
    Session,
    SessionParticipation,
    Sphere,
    SphereMembership,
    SphereSubscription,
)
from ludamus.pacts.dashboard import (
    DashboardCardDTO,
    DashboardRepositoryProtocol,
    DashboardRole,
    DashboardSphereDTO,
)
from ludamus.pacts.legacy import EncountersPolicy, SessionParticipationStatus

if TYPE_CHECKING:
    from datetime import datetime

_start_time = attrgetter("start_time")


def _session_card(
    participation: SessionParticipation, *, role: DashboardRole
) -> DashboardCardDTO:
    session = participation.session
    event = session.event
    sphere = event.sphere
    item = session.agenda_item
    return DashboardCardDTO(
        title=session.title,
        url=absolute_url(
            reverse(
                "web:chronology:session-enrollment",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            ),
            domain=sphere.site.domain,
        ),
        start_time=item.start_time,
        origin_name=event.name,
        role=role,
        cover_url=session.cover_image_url or event.cover_image_url,
        place=item.space.name,
        capacity=session.participants_limit,
    )


def _encounter_card(encounter: Encounter, *, role: DashboardRole) -> DashboardCardDTO:
    return DashboardCardDTO(
        title=encounter.title,
        url=absolute_url(
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
            domain=encounter.sphere.site.domain,
        ),
        start_time=encounter.start_time,
        origin_name=encounter.sphere.name,
        role=role,
        cover_url=encounter.header_image_url,
        place=encounter.place,
        attending_count=getattr(encounter, "rsvp_total", 0),
        capacity=encounter.max_participants,
    )


def _held_sessions(user_id: int, *, now: datetime) -> list[SessionParticipation]:
    return list(
        SessionParticipation.objects.filter(
            user_id=user_id,
            status=SessionParticipationStatus.CONFIRMED,
            session__agenda_item__start_time__gte=now,
        ).select_related("session__agenda_item__space", "session__event__sphere__site")
    )


def _held_encounters(user_id: int, *, now: datetime) -> list[Encounter]:
    return list(
        Encounter.objects.filter(
            Q(creator_id=user_id) | Q(rsvps__user_id=user_id), start_time__gte=now
        )
        .select_related("sphere__site")
        .annotate(rsvp_total=Count("rsvps", distinct=True))
        .distinct()
    )


class DashboardRepository(DashboardRepositoryProtocol):
    @staticmethod
    def list_agenda(user_id: int, *, now: datetime) -> list[DashboardCardDTO]:
        """List everything this member holds a place at, soonest first.

        Returns:
            Confirmed programme seats and encounters they organise or hold an
            RSVP to. Uncapped on purpose — the ceiling is what one person can
            actually attend, which no convention pushes far.
        """
        sessions = [
            _session_card(participation, role=DashboardRole.SIGNED_UP)
            for participation in _held_sessions(user_id, now=now)
        ]
        encounters = [
            _encounter_card(
                encounter,
                role=(
                    DashboardRole.ORGANIZING
                    if encounter.creator_id == user_id
                    else DashboardRole.SIGNED_UP
                ),
            )
            for encounter in _held_encounters(user_id, now=now)
        ]
        return sorted(sessions + encounters, key=_start_time)

    @staticmethod
    def list_open_encounters(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardCardDTO]:
        """List encounters anyone may join, across every sphere that runs them.

        Returns:
            Up to ``limit`` upcoming listed encounters, soonest first, minus
            the ones this member already organises or holds an RSVP to — those
            are on their agenda, and a dashboard that offers you what you
            already have is noise.
        """
        encounters = (
            Encounter.objects.filter(
                is_public=True,
                start_time__gte=now,
                sphere__encounters_policy__in=(
                    EncountersPolicy.MANAGERS,
                    EncountersPolicy.EVERYONE,
                ),
            )
            .exclude(creator_id=user_id)
            .exclude(rsvps__user_id=user_id)
            .select_related("sphere__site")
            .annotate(rsvp_total=Count("rsvps", distinct=True))
            .order_by("start_time")[:limit]
        )
        return [
            _encounter_card(encounter, role=DashboardRole.OPEN)
            for encounter in encounters
        ]

    @staticmethod
    def list_sphere_feed(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardCardDTO]:
        """List what is coming up in the spheres this member already plays in.

        Returns:
            Up to ``limit`` published events, soonest first, from spheres they
            subscribe to, manage, or hold something in.
        """
        sphere_ids = _sphere_ids_with_ties(user_id)
        events = (
            Event.objects.filter(
                sphere_id__in=sphere_ids,
                publication_time__isnull=False,
                publication_time__lte=now,
                end_time__gte=now,
            )
            .select_related("sphere__site")
            .order_by("start_time")[:limit]
        )
        return [
            DashboardCardDTO(
                title=event.name,
                url=absolute_url(
                    reverse("web:chronology:event", kwargs={"slug": event.slug}),
                    domain=event.sphere.site.domain,
                ),
                start_time=event.start_time,
                origin_name=event.sphere.name,
                role=DashboardRole.OPEN,
                cover_url=event.cover_image_url,
                place=event.address,
            )
            for event in events
        ]

    @staticmethod
    def list_spheres_to_discover(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardSphereDTO]:
        """List the spheres worth following, subscribed ones included.

        Returns:
            Up to ``limit`` spheres with something published ahead of them,
            busiest first, each saying whether this member already follows it —
            the button is a toggle, so a followed sphere stays on the list.
            The root sphere is the page's own home, never its own suggestion.
        """
        subscribed = set(
            SphereSubscription.objects.filter(user_id=user_id).values_list(
                "sphere_id", flat=True
            )
        )
        spheres = (
            Sphere.objects.select_related("site")
            .filter(is_listed=True)
            .exclude(site_id=settings.SITE_ID)
            .annotate(
                upcoming=Count(
                    "events",
                    filter=Q(
                        events__publication_time__isnull=False,
                        events__publication_time__lte=now,
                        events__end_time__gte=now,
                    ),
                    distinct=True,
                )
            )
            .filter(upcoming__gt=0)
            .order_by("-upcoming", "name")[:limit]
        )
        return [
            DashboardSphereDTO(
                pk=sphere.pk,
                name=sphere.name,
                url=absolute_url("/", domain=sphere.site.domain),
                logo_url=sphere.logo_url,
                upcoming_count=sphere.upcoming,
                is_subscribed=sphere.pk in subscribed,
            )
            for sphere in spheres
        ]


def _sphere_ids_with_ties(user_id: int) -> set[int]:
    # Every reason a sphere is "yours": you asked to hear from it, you run it,
    # or you hold something in it.
    return (
        set(
            SphereSubscription.objects.filter(user_id=user_id).values_list(
                "sphere_id", flat=True
            )
        )
        | set(
            SphereMembership.objects.filter(user_id=user_id).values_list(
                "sphere_id", flat=True
            )
        )
        | set(
            Session.objects.filter(session_participations__user_id=user_id).values_list(
                "event__sphere_id", flat=True
            )
        )
        | set(
            Encounter.objects.filter(
                Q(creator_id=user_id) | Q(rsvps__user_id=user_id)
            ).values_list("sphere_id", flat=True)
        )
    )
