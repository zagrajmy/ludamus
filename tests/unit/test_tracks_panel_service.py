from unittest.mock import MagicMock

import pytest

from ludamus.mills.tracks import TracksPanelService
from ludamus.pacts import NotFoundError
from ludamus.pacts.tracks import TrackFormData, TrackSelectionInvalidError


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

    def test_list_tracks_delegates_to_repository(self, service, tracks):
        listed = [MagicMock()]
        tracks.list_by_event_with_assignments.return_value = listed

        result = service.list_tracks(42)

        assert result == listed
        tracks.list_by_event_with_assignments.assert_called_once_with(42)

    def test_get_form_context_bundles_event_spaces_and_sphere_managers(
        self, service, spaces, spheres
    ):
        event_spaces = [MagicMock(pk=1)]
        sphere_managers = [MagicMock(pk=7)]
        spaces.list_by_event.return_value = event_spaces
        spheres.list_managers.return_value = sphere_managers

        context = service.get_form_context(event_pk=42, sphere_id=3)

        assert context.spaces == event_spaces
        assert context.managers == sphere_managers
        spaces.list_by_event.assert_called_once_with(42)
        spheres.list_managers.assert_called_once_with(3)

    def test_get_edit_form_context_skips_assignment_reads(
        self, service, tracks, spaces, spheres
    ):
        track = MagicMock(pk=5)
        event_spaces = [MagicMock(pk=1)]
        sphere_managers = [MagicMock(pk=7)]
        tracks.read_by_slug.return_value = track
        spaces.list_by_event.return_value = event_spaces
        spheres.list_managers.return_value = sphere_managers

        context = service.get_edit_form_context(
            event_pk=42, sphere_id=3, track_slug="alpha"
        )

        assert context.track is track
        assert context.spaces == event_spaces
        assert context.managers == sphere_managers
        tracks.read_by_slug.assert_called_once_with(42, "alpha")
        tracks.list_space_pks.assert_not_called()
        tracks.list_manager_pks.assert_not_called()

    def test_get_edit_form_context_foreign_track_slug_raises_not_found(
        self, service, tracks
    ):
        tracks.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.get_edit_form_context(
                event_pk=42, sphere_id=3, track_slug="foreign"
            )

    def test_get_edit_context_reads_event_scoped_track_with_assignments(
        self, service, tracks, spaces, spheres
    ):
        track = MagicMock(pk=5)
        tracks.read_by_slug.return_value = track
        tracks.list_space_pks.return_value = [1]
        tracks.list_manager_pks.return_value = [7]
        spaces.list_by_event.return_value = []
        spheres.list_managers.return_value = []

        context = service.get_edit_context(event_pk=42, sphere_id=3, track_slug="alpha")

        assert context.track is track
        assert context.selected_space_pks == [1]
        assert context.selected_manager_pks == [7]
        tracks.read_by_slug.assert_called_once_with(42, "alpha")
        tracks.list_space_pks.assert_called_once_with(5)
        tracks.list_manager_pks.assert_called_once_with(5)

    def test_get_edit_context_foreign_track_slug_raises_not_found(
        self, service, tracks
    ):
        tracks.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.get_edit_context(event_pk=42, sphere_id=3, track_slug="foreign")

    def test_create_rejects_foreign_space_and_manager_pks(
        self, service, transaction, tracks, spaces, spheres
    ):
        spaces.list_by_event.return_value = [MagicMock(pk=1), MagicMock(pk=2)]
        spheres.list_managers.return_value = [MagicMock(pk=7)]

        with pytest.raises(TrackSelectionInvalidError):
            service.create(
                event_pk=42,
                sphere_id=3,
                data=_data(space_pks=[1, 2, 999], manager_pks=[7, 888]),
            )

        transaction.atomic.assert_called_once_with()
        tracks.create.assert_not_called()

    def test_update_rejects_foreign_submitted_pks(
        self, service, transaction, tracks, spaces, spheres
    ):
        tracks.read_by_slug.return_value = MagicMock(pk=5)
        spaces.list_by_event.return_value = [MagicMock(pk=2)]
        spheres.list_managers.return_value = []

        with pytest.raises(TrackSelectionInvalidError):
            service.update(
                event_pk=42,
                sphere_id=3,
                track_slug="alpha",
                data=_data(
                    name="Beta", is_public=False, space_pks=[2, 999], manager_pks=[888]
                ),
            )

        transaction.atomic.assert_called_once_with()
        tracks.read_by_slug.assert_called_once_with(42, "alpha")
        tracks.update.assert_not_called()

    def test_update_foreign_track_slug_raises_without_side_effects(
        self, service, tracks
    ):
        tracks.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.update(event_pk=42, sphere_id=3, track_slug="foreign", data=_data())

        tracks.update.assert_not_called()

    def test_delete_deletes_event_scoped_track(self, service, transaction, tracks):
        tracks.read_by_slug.return_value = MagicMock(pk=5)

        service.delete(event_pk=42, track_slug="alpha")

        transaction.atomic.assert_called_once_with()
        tracks.read_by_slug.assert_called_once_with(42, "alpha")
        tracks.delete.assert_called_once_with(5)

    def test_delete_foreign_track_slug_raises_without_side_effects(
        self, service, tracks
    ):
        tracks.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.delete(event_pk=42, track_slug="foreign")

        tracks.delete.assert_not_called()
