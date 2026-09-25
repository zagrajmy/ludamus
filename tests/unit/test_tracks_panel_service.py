from unittest.mock import MagicMock

import pytest

from ludamus.mills.tracks import TracksPanelService
from ludamus.pacts.tracks import (
    DuplicateTrackNameError,
    TrackFormData,
    TrackSelectionInvalidError,
)


def _data(*, space_pks=()):
    return TrackFormData(
        name="Alpha", is_public=True, space_pks=list(space_pks), manager_pks=[]
    )


class TestTracksPanelService:
    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def tracks(self):
        return MagicMock()

    @pytest.fixture
    def spaces(self):
        return MagicMock()

    @pytest.fixture
    def spheres(self):
        return MagicMock()

    @pytest.fixture
    def service(self, transaction, tracks, spaces, spheres):
        return TracksPanelService(
            transaction=transaction, tracks=tracks, spaces=spaces, spheres=spheres
        )

    def test_find_or_create_refuses_a_foreign_space_even_when_the_name_is_taken(
        self, service, tracks, spaces
    ):
        tracks.find_by_event_and_name.return_value = MagicMock(pk=5)
        spaces.list_by_event.return_value = [MagicMock(pk=1)]

        with pytest.raises(TrackSelectionInvalidError):
            service.find_or_create(
                event_pk=42, sphere_id=3, data=_data(space_pks=(99,))
            )

        tracks.create.assert_not_called()

    def test_find_or_create_reraises_when_the_race_winner_cannot_be_found(
        self, service, tracks, spaces, spheres
    ):
        tracks.find_by_event_and_name.side_effect = [None, None]
        tracks.create.side_effect = DuplicateTrackNameError
        spaces.list_by_event.return_value = []
        spheres.list_managers.return_value = []

        with pytest.raises(DuplicateTrackNameError):
            service.find_or_create(event_pk=42, sphere_id=3, data=_data())

    def test_find_or_create_yields_to_the_winner_of_a_concurrent_create(
        self, service, tracks, spaces, spheres
    ):
        winner = MagicMock(pk=11)
        tracks.find_by_event_and_name.side_effect = [None, winner]
        tracks.create.side_effect = DuplicateTrackNameError
        spaces.list_by_event.return_value = []
        spheres.list_managers.return_value = []

        assert service.find_or_create(event_pk=42, sphere_id=3, data=_data()) is winner
