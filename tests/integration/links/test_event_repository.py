from datetime import UTC, datetime, timedelta

import pytest

from ludamus.links.db.django.repositories import EventRepository, LandingStatsRepository
from ludamus.pacts.event import EventCreateData, LandingStatsDTO
from ludamus.pacts.services import DatabaseConstraintError
from tests.integration.conftest import EventFactory, SessionFactory


@pytest.mark.usefixtures("event")
def test_exists_for_sphere_ignores_other_spheres(sphere, non_root_sphere):
    assert EventRepository.exists_for_sphere(sphere.pk) is True
    assert EventRepository.exists_for_sphere(non_root_sphere.pk) is False


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
            sphere=non_root_sphere, start_time=now, cover_image="events/newest.png"
        )

        conventions = LandingStatsRepository.list_conventions(3)

        assert [c.name for c in conventions] == [non_root_sphere.name]
        assert conventions[0].cover_image_url.endswith("events/newest.png")
        assert conventions[0].domain == non_root_sphere.site.domain

    def test_conventions_skip_spheres_without_events(self, sphere, non_root_sphere):
        del sphere, non_root_sphere

        assert LandingStatsRepository.list_conventions(3) == []
