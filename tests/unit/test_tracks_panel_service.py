from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.tracks import TracksPanelService
from ludamus.pacts.legacy import TrackCreateData, TrackUpdateData
from ludamus.pacts.tracks import (
    DuplicateTrackNameError,
    TrackFormData,
    TrackSelectionInvalidError,
)


def _data(*, name="Alpha", is_public=True, space_pks=(), manager_pks=()):
    return TrackFormData(
        name=name,
        is_public=is_public,
        space_pks=list(space_pks),
        manager_pks=list(manager_pks),
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

    def test_create_writes_the_selection_scoped_and_sorted(
        self, service, tracks, spaces, spheres
    ):
        spaces.list_by_event.return_value = [MagicMock(pk=1), MagicMock(pk=2)]
        spheres.list_managers.return_value = [MagicMock(pk=7), MagicMock(pk=8)]

        created = service.create(
            event_pk=42,
            sphere_id=3,
            data=_data(is_public=False, space_pks=(2, 1), manager_pks=(8, 7)),
        )

        assert created is tracks.create.return_value
        spaces.list_by_event.assert_called_once_with(42)
        spheres.list_managers.assert_called_once_with(3)
        tracks.create.assert_called_once_with(
            TrackCreateData(
                event_pk=42,
                name="Alpha",
                is_public=False,
                space_pks=[1, 2],
                manager_pks=[7, 8],
            )
        )

    def test_update_writes_the_selection_scoped_and_sorted(
        self, service, tracks, spaces, spheres
    ):
        tracks.read_by_slug.return_value = MagicMock(pk=5)
        spaces.list_by_event.return_value = [MagicMock(pk=1), MagicMock(pk=2)]
        spheres.list_managers.return_value = [MagicMock(pk=7)]

        service.update(
            event_pk=42,
            sphere_id=3,
            track_slug="alpha",
            data=_data(name="Beta", space_pks=(2, 1), manager_pks=(7,)),
        )

        tracks.read_by_slug.assert_called_once_with(42, "alpha")
        spaces.list_by_event.assert_called_once_with(42)
        spheres.list_managers.assert_called_once_with(3)
        tracks.update.assert_called_once_with(
            5,
            TrackUpdateData(
                name="Beta", is_public=True, space_pks=[1, 2], manager_pks=[7]
            ),
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

    def test_find_or_create_makes_the_track_when_the_name_is_free(
        self, service, tracks, spaces, spheres
    ):
        created = MagicMock(pk=9)
        tracks.find_by_event_and_name.return_value = None
        tracks.create.return_value = created
        spaces.list_by_event.return_value = []
        spheres.list_managers.return_value = []

        assert service.find_or_create(event_pk=42, sphere_id=3, data=_data()) is created
        tracks.create.assert_called_once_with(
            TrackCreateData(
                event_pk=42, name="Alpha", is_public=True, space_pks=[], manager_pks=[]
            )
        )

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
        assert tracks.find_by_event_and_name.call_args_list == [
            call(42, "Alpha"),
            call(42, "Alpha"),
        ]
