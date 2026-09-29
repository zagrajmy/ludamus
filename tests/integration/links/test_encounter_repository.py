from datetime import UTC, datetime, timedelta

from ludamus.links.db.django.repositories import EncounterRepository
from tests.integration.conftest import EncounterFactory, EncounterRSVPFactory


def test_exists_for_sphere_ignores_other_spheres(sphere, non_root_sphere):
    EncounterFactory(sphere=sphere, start_time=datetime.now(UTC) + timedelta(days=1))

    assert EncounterRepository.exists_for_sphere(sphere.pk) is True
    assert EncounterRepository.exists_for_sphere(non_root_sphere.pk) is False


def test_list_visible_upcoming_filters_and_orders(sphere, non_root_sphere):
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

    result = EncounterRepository.list_visible_upcoming(sphere.pk, None)

    assert [encounter.pk for encounter in result] == [sooner.pk, later.pk]


def test_list_visible_upcoming_adds_own_and_rsvpd_encounters(sphere, active_user):
    now = datetime.now(UTC)
    listed = EncounterFactory(
        sphere=sphere, is_public=True, start_time=now + timedelta(days=4)
    )
    mine = EncounterFactory(
        sphere=sphere,
        creator=active_user,
        is_public=False,
        start_time=now + timedelta(days=3),
    )
    invited = EncounterFactory(
        sphere=sphere, is_public=False, start_time=now + timedelta(days=2)
    )
    EncounterRSVPFactory(encounter=invited, user=active_user)
    unrelated = EncounterFactory(
        sphere=sphere, is_public=False, start_time=now + timedelta(days=1)
    )

    result = EncounterRepository.list_visible_upcoming(sphere.pk, active_user.pk)

    assert [encounter.pk for encounter in result] == [invited.pk, mine.pk, listed.pk]
    assert unrelated.pk not in {encounter.pk for encounter in result}


def test_list_visible_past_orders_most_recent_first(sphere, active_user):
    now = datetime.now(UTC)
    older = EncounterFactory(
        sphere=sphere,
        creator=active_user,
        start_time=now - timedelta(days=5),
        end_time=now - timedelta(days=5) + timedelta(hours=2),
    )
    recent = EncounterFactory(
        sphere=sphere,
        is_public=True,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(hours=20),
    )
    EncounterFactory(sphere=sphere, start_time=now + timedelta(days=1))

    result = EncounterRepository.list_visible_past(sphere.pk, active_user.pk, limit=10)

    assert [encounter.pk for encounter in result] == [recent.pk, older.pk]


def test_an_encounter_in_progress_is_still_upcoming(sphere):
    now = datetime.now(UTC)
    running = EncounterFactory(
        sphere=sphere,
        is_public=True,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
    )

    assert [
        e.pk for e in EncounterRepository.list_visible_upcoming(sphere.pk, None)
    ] == [running.pk]
    assert EncounterRepository.list_visible_past(sphere.pk, None, limit=10) == []


def test_an_encounter_without_an_end_time_ends_when_it_starts(sphere):
    now = datetime.now(UTC)
    ahead = EncounterFactory(
        sphere=sphere, is_public=True, start_time=now + timedelta(days=1), end_time=None
    )
    behind = EncounterFactory(
        sphere=sphere, is_public=True, start_time=now - timedelta(days=1), end_time=None
    )

    assert [
        e.pk for e in EncounterRepository.list_visible_upcoming(sphere.pk, None)
    ] == [ahead.pk]
    assert [
        e.pk for e in EncounterRepository.list_visible_past(sphere.pk, None, limit=10)
    ] == [behind.pk]


def test_list_visible_past_stops_at_the_limit(sphere):
    limit = 2
    now = datetime.now(UTC)
    for days in range(1, 5):
        EncounterFactory(
            sphere=sphere,
            is_public=True,
            start_time=now - timedelta(days=days),
            end_time=now - timedelta(days=days) + timedelta(hours=1),
        )

    result = EncounterRepository.list_visible_past(sphere.pk, None, limit=limit)

    assert len(result) == limit


def test_list_visible_hides_private_encounters_from_anonymous(sphere):
    now = datetime.now(UTC)
    EncounterFactory(sphere=sphere, is_public=False, start_time=now + timedelta(days=1))

    assert EncounterRepository.list_visible_upcoming(sphere.pk, None) == []
