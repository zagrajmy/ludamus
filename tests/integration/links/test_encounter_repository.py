from datetime import UTC, datetime, timedelta

from ludamus.links.db.django.repositories import EncounterRepository
from tests.integration.conftest import EncounterFactory


def test_exists_for_sphere_ignores_other_spheres(sphere, non_root_sphere):
    EncounterFactory(sphere=sphere, start_time=datetime.now(UTC) + timedelta(days=1))

    assert EncounterRepository.exists_for_sphere(sphere.pk) is True
    assert EncounterRepository.exists_for_sphere(non_root_sphere.pk) is False


def test_list_public_upcoming_filters_and_orders(sphere, non_root_sphere):
    now = datetime.now(UTC)
    later = EncounterFactory(
        sphere=sphere, is_public=True, start_time=now + timedelta(days=5)
    )
    sooner = EncounterFactory(
        sphere=sphere, is_public=True, start_time=now + timedelta(days=2)
    )
    EncounterFactory(sphere=sphere, is_public=False, start_time=now + timedelta(days=1))
    EncounterFactory(
        sphere=sphere,
        is_public=True,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(hours=1),
    )
    EncounterFactory(
        sphere=non_root_sphere, is_public=True, start_time=now + timedelta(days=1)
    )

    result = EncounterRepository.list_public_upcoming(sphere.pk)

    assert [encounter.pk for encounter in result] == [sooner.pk, later.pk]
