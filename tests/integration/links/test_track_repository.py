import pytest
from django.db import IntegrityError

from ludamus.links.db.django.models import Track
from ludamus.links.db.django.repositories import TrackRepository
from ludamus.pacts.legacy import TrackCreateData, TrackUpdateData
from ludamus.pacts.tracks import DuplicateTrackNameError
from tests.integration.conftest import EventFactory


def _create_data(*, event_pk, name):
    return TrackCreateData(
        event_pk=event_pk, name=name, is_public=True, space_pks=[], manager_pks=[]
    )


class TestTrackRepositoryGetOrCreateBySlug:
    def test_creates_a_track_with_the_given_name_and_slug(self):
        event = EventFactory.create()

        pk = TrackRepository.get_or_create_by_slug(event.pk, "RPG", "rpg")

        track = Track.objects.get(pk=pk)
        assert track.name == "RPG"
        assert track.slug == "rpg"
        assert track.event_id == event.pk

    def test_reuses_an_existing_track_by_slug(self):
        event = EventFactory.create()
        first = TrackRepository.get_or_create_by_slug(event.pk, "RPG", "rpg")

        second = TrackRepository.get_or_create_by_slug(event.pk, "RPG sessions", "rpg")

        assert second == first
        assert Track.objects.filter(event=event).count() == 1


class TestTrackRepositoryDuplicateName:
    def test_create_reports_a_name_another_track_holds_in_any_case(self):
        event = EventFactory.create()
        Track.objects.create(event=event, name="RPG", slug="rpg")

        with pytest.raises(DuplicateTrackNameError):
            TrackRepository().create(_create_data(event_pk=event.pk, name="rpg"))

        assert Track.objects.filter(event=event).count() == 1

    def test_create_allows_the_same_name_in_another_event(self):
        event = EventFactory.create()
        other_event = EventFactory.create()
        Track.objects.create(event=other_event, name="RPG", slug="rpg")

        track = TrackRepository().create(_create_data(event_pk=event.pk, name="RPG"))

        assert track.name == "RPG"

    def test_update_reports_a_name_another_track_holds_in_any_case(self):
        event = EventFactory.create()
        Track.objects.create(event=event, name="RPG", slug="rpg")
        renamed = Track.objects.create(event=event, name="Board games", slug="board")

        with pytest.raises(DuplicateTrackNameError):
            TrackRepository().update(
                renamed.pk,
                TrackUpdateData(
                    name="rpg", is_public=True, space_pks=[], manager_pks=[]
                ),
            )

        renamed.refresh_from_db()
        assert renamed.name == "Board games"

    def test_update_keeps_the_track_its_own_name(self):
        event = EventFactory.create()
        track = Track.objects.create(event=event, name="RPG", slug="rpg")

        updated = TrackRepository().update(
            track.pk,
            TrackUpdateData(name="RPG", is_public=False, space_pks=[], manager_pks=[]),
        )

        assert updated.is_public is False


class TestTrackRepositoryReraisesUnrelatedIntegrityError:
    @staticmethod
    def _raise_unrelated(*_args, **_kwargs):
        raise IntegrityError("FOREIGN KEY constraint failed")

    def test_create_reraises_a_constraint_failure_of_another_kind(self, monkeypatch):
        event = EventFactory.create()
        monkeypatch.setattr(Track.objects, "create", self._raise_unrelated)

        with pytest.raises(IntegrityError):
            TrackRepository().create(_create_data(event_pk=event.pk, name="RPG"))

    def test_update_reraises_a_constraint_failure_of_another_kind(self, monkeypatch):
        event = EventFactory.create()
        track = Track.objects.create(event=event, name="RPG", slug="rpg")
        monkeypatch.setattr(Track, "save", self._raise_unrelated)

        with pytest.raises(IntegrityError):
            TrackRepository().update(
                track.pk,
                TrackUpdateData(
                    name="Board games", is_public=True, space_pks=[], manager_pks=[]
                ),
            )
