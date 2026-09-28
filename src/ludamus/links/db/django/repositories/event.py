from django.db.models import OuterRef, Subquery
from django.utils import timezone

from ludamus.links.db.django.models import Event, Session, Sphere, suggested_spheres
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
    def list_conventions(domains: tuple[str, ...]) -> list[LandingConventionDTO]:
        """List the chosen conventions, in the order they were chosen.

        Returns:
            The public spheres among ``domains`` that have a published event,
            each carrying its newest one's slug and cover image. A sphere that
            went private or has nothing published yet drops out rather than
            leaving a dead card.
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
            .filter(suggested_spheres(), site__domain__in=domains)
            .annotate(
                cover=Subquery(newest.values("cover_image")[:1]),
                event_slug=Subquery(newest.values("slug")[:1]),
            )
            .filter(event_slug__isnull=False)
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
            for sphere in sorted(spheres, key=lambda s: domains.index(s.site.domain))
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
