from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.repositories import EventRepository, LandingStatsRepository
from ludamus.pacts.event import EventCreateData, LandingStatsDTO
from ludamus.pacts.services import DatabaseConstraintError
from tests.integration.conftest import EventFactory, SessionFactory


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

        conventions = LandingStatsRepository.list_conventions(3)

        assert [c.name for c in conventions] == [non_root_sphere.name]
        assert conventions[0].cover_image_url.endswith("events/newest.png")
        assert conventions[0].domain == non_root_sphere.site.domain
        assert conventions[0].event_slug == "newest"

    def test_conventions_leave_out_unlisted_spheres(self, non_root_sphere):
        EventFactory(sphere=non_root_sphere)
        non_root_sphere.is_listed = False
        non_root_sphere.save()

        assert LandingStatsRepository.list_conventions(3) == []

    def test_conventions_skip_spheres_without_events(self, sphere, non_root_sphere):
        del sphere, non_root_sphere

        assert LandingStatsRepository.list_conventions(3) == []

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

        conventions = LandingStatsRepository.list_conventions(3)

        assert [c.name for c in conventions] == [non_root_sphere.name]
        assert conventions[0].cover_image_url.endswith("events/published.png")

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
