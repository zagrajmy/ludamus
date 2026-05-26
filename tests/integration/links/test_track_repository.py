from ludamus.adapters.db.django.models import Track
from ludamus.links.db.django.repositories import TrackRepository
from tests.integration.conftest import EventFactory


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
