from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from ludamus.links.db.django.models import Event, Session, Sphere
from ludamus.pacts.event import (
    LandingConventionDTO,
    LandingStatsDTO,
    LandingStatsRepositoryProtocol,
)


class LandingStatsRepository(LandingStatsRepositoryProtocol):
    @staticmethod
    def count_landing_stats() -> LandingStatsDTO:
        # Everything a sphere has put into Zagrajmy, drafts included — the
        # claim is about work the tool holds, not about what is published.
        # Soft-deleted sessions are excluded: `objects` is the alive manager.
        return LandingStatsDTO(
            events=Event.objects.count(), sessions=Session.objects.count()
        )

    @staticmethod
    def list_conventions(limit: int) -> list[LandingConventionDTO]:
        """List spheres that run events, newest first, with their cover art.

        Returns:
            Up to ``limit`` listed conventions, each carrying its newest
            event's slug and cover image. The root sphere is the landing
            itself, so it is not one of its own conventions.
        """
        # Same predicate as Event.is_published: a draft or not-yet-published
        # event must not surface its cover art or domain on the public
        # landing page just because it exists.
        newest = Event.objects.filter(
            sphere=OuterRef("pk"),
            publication_time__isnull=False,
            publication_time__lte=timezone.now(),
        ).order_by("-start_time")
        spheres = (
            Sphere.objects.select_related("site")
            .filter(is_listed=True)
            .exclude(site_id=settings.SITE_ID)
            .annotate(
                cover=Subquery(newest.values("cover_image")[:1]),
                event_slug=Subquery(newest.values("slug")[:1]),
                newest_start=Subquery(newest.values("start_time")[:1]),
            )
            .filter(newest_start__isnull=False)
            .order_by("-newest_start")[:limit]
        )
        # The URL comes from the model's own property rather than from the
        # storage directly, so it cannot drift from how an Event renders its
        # cover anywhere else.
        return [
            LandingConventionDTO(
                name=sphere.name,
                domain=sphere.site.domain,
                event_slug=sphere.event_slug,
                cover_image_url=Event(cover_image=sphere.cover).cover_image_url,
            )
            for sphere in spheres
        ]

    @staticmethod
    def read_newest_published_slug(sphere_id: int) -> str | None:
        """Name the sphere's newest event a visitor can already open.

        Returns:
            The slug of the published event with the latest start, or None
            when the sphere runs no published event.
        """
        # Same predicate as Event.is_published: a draft is not a page anyone
        # can be sent to.
        return (
            Event.objects.filter(
                sphere_id=sphere_id,
                publication_time__isnull=False,
                publication_time__lte=timezone.now(),
            )
            .order_by("-start_time")
            .values_list("slug", flat=True)
            .first()
        )
