from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.repositories import EventRepository, LandingStatsRepository
from ludamus.pacts.event import EventCreateData, LandingStatsDTO
from ludamus.pacts.multiverse import SphereVisibility
from ludamus.pacts.services import DatabaseConstraintError
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SiteFactory,
    SphereFactory,
)


def test_create_does_not_report_a_date_constraint_as_a_slug_conflict(sphere):
    start_time = datetime(2027, 9, 17, 16, tzinfo=UTC)
    data = EventCreateData(
        name="Invalid publication",
        slug="invalid-publication",
        description="",
        start_time=start_time,
        end_time=start_time + timedelta(days=2),
        publication_time=start_time + timedelta(days=1),
        auto_confirm_sessions=False,
    )

    with pytest.raises(DatabaseConstraintError):
        EventRepository.create(sphere.pk, data)


class TestLandingStatsRepository:
    def test_counts_every_event_and_live_session(self, sphere, event):
        SessionFactory(category__event=event)
        deleted = SessionFactory(category__event=event)
        deleted.soft_delete()
        EventFactory(sphere=sphere, publication_time=None)

        stats = LandingStatsRepository.count_landing_stats()

        assert stats == LandingStatsDTO(events=2, sessions=1)

    def test_conventions_carry_the_newest_event_cover(
        self, sphere, non_root_sphere, event
    ):
        del event
        now = datetime.now(UTC)
        EventFactory(
            sphere=non_root_sphere,
            start_time=now - timedelta(days=30),
            cover_image="events/old.png",
        )

        EventFactory(
            sphere=non_root_sphere,
            slug="newest",
            start_time=now,
            cover_image="events/newest.png",
        )

        conventions = LandingStatsRepository.list_conventions(
            (non_root_sphere.site.domain,)
        )

        assert [c.name for c in conventions] == [non_root_sphere.name]
        assert conventions[0].cover_image_url.endswith("events/newest.png")
        assert conventions[0].domain == non_root_sphere.site.domain
        assert conventions[0].event_slug == "newest"

    @pytest.mark.parametrize(
        "visibility", (SphereVisibility.UNLISTED, SphereVisibility.PRIVATE)
    )
    def test_conventions_leave_out_spheres_that_are_not_public(
        self, non_root_sphere, visibility
    ):
        EventFactory(sphere=non_root_sphere)
        non_root_sphere.visibility = visibility
        non_root_sphere.save()

        assert (
            LandingStatsRepository.list_conventions((non_root_sphere.site.domain,))
            == []
        )

    def test_conventions_skip_spheres_without_events(self, sphere, non_root_sphere):
        del sphere

        assert (
            LandingStatsRepository.list_conventions((non_root_sphere.site.domain,))
            == []
        )

    def test_conventions_never_carry_an_unpublished_event_cover(
        self, sphere, non_root_sphere, event
    ):
        del event
        now = datetime.now(UTC)
        EventFactory(
            sphere=non_root_sphere,
            start_time=now - timedelta(days=30),
            cover_image="events/published.png",
        )
        EventFactory(
            sphere=non_root_sphere,
            start_time=now + timedelta(days=1),
            publication_time=now + timedelta(days=1),
            cover_image="events/draft.png",
        )

        conventions = LandingStatsRepository.list_conventions(
            (non_root_sphere.site.domain,)
        )

        assert [c.name for c in conventions] == [non_root_sphere.name]
        assert conventions[0].cover_image_url.endswith("events/published.png")

    def test_conventions_keep_the_chosen_order_and_nothing_else(self):
        kapitularz, bachanalia, o2f, other = (
            SphereFactory(site=SiteFactory(domain=f"{name}.example.com"))
            for name in ("kapitularz", "bachanalia", "o2f", "other")
        )
        now = datetime.now(UTC)
        # Start times run against the chosen order, so a sort by date fails.
        for days, sphere in enumerate((o2f, bachanalia, kapitularz, other)):
            EventFactory(sphere=sphere, start_time=now + timedelta(days=days))

        conventions = LandingStatsRepository.list_conventions(
            ("kapitularz.example.com", "bachanalia.example.com", "o2f.example.com")
        )

        assert [c.name for c in conventions] == [
            kapitularz.name,
            bachanalia.name,
            o2f.name,
        ]

    def test_newest_published_slug_is_the_latest_start_a_visitor_can_open(
        self, sphere, non_root_sphere
    ):
        now = datetime.now(UTC)
        EventFactory(sphere=sphere, slug="older", start_time=now - timedelta(days=30))
        EventFactory(sphere=sphere, slug="newest", start_time=now + timedelta(days=7))
        EventFactory(
            sphere=sphere,
            slug="draft",
            start_time=now + timedelta(days=60),
            publication_time=None,
        )
        EventFactory(
            sphere=sphere,
            slug="scheduled",
            start_time=now + timedelta(days=60),
            publication_time=now + timedelta(days=1),
        )
        EventFactory(
            sphere=non_root_sphere, slug="foreign", start_time=now + timedelta(days=90)
        )

        assert LandingStatsRepository.read_newest_published_slug(sphere.pk) == "newest"

    def test_newest_published_slug_is_none_without_a_published_event(self, sphere):
        EventFactory(sphere=sphere, publication_time=None)

        assert LandingStatsRepository.read_newest_published_slug(sphere.pk) is None
