from datetime import UTC, datetime
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.tracks import TracksPanelService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.legacy import (
    SpaceDTO,
    TrackCreateData,
    TrackDTO,
    TrackListItemDTO,
    TrackUpdateData,
)
from ludamus.pacts.tracks import (
    DuplicateTrackNameError,
    TrackFormData,
    TrackSelectionInvalidError,
)
from tests.unit.factories import FakeTransaction

EVENT_PK = 42
NOW = datetime(2026, 6, 4, 12, tzinfo=UTC)


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


def _user(pk):
    return UserDTO(
        avatar_url="",
        date_joined=NOW,
        discord_username="",
        email=f"user{pk}@example.test",
        full_name="",
        is_active=True,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name="",
        pk=pk,
        slug=f"user-{pk}",
        use_gravatar=True,
        user_type=UserType.ACTIVE,
        username=f"user{pk}",
    )


def _space(pk):
    return SpaceDTO(
        capacity=None,
        creation_time=NOW,
        modification_time=NOW,
        name=f"Sala {pk}",
        order=0,
        pk=pk,
        slug=f"sala-{pk}",
    )


class FakeSpaces:
    def __init__(self, pks):
        self.pks = list(pks)

    def list_by_event(self, event_pk):
        del event_pk
        return [_space(pk) for pk in self.pks]


class FakeSpheres:
    def __init__(self, pks):
        self.pks = list(pks)

    def list_managers(self, sphere_id):
        del sphere_id
        return [_user(pk) for pk in self.pks]


class FakeTracks:
    def __init__(self):
        # pk -> (TrackDTO, space_pks, manager_pks)
        self.rows: dict[int, tuple[TrackDTO, list[int], list[int]]] = {}

    def _track(self, pk, *, name, is_public):
        return TrackDTO(
            creation_time=NOW,
            event_id=EVENT_PK,
            is_public=is_public,
            modification_time=NOW,
            name=name,
            pk=pk,
            slug=name.lower(),
        )

    def create(self, data):
        pk = max(self.rows, default=0) + 1
        track = self._track(pk, name=data["name"], is_public=data["is_public"])
        self.rows[pk] = (track, data["space_pks"], data["manager_pks"])
        return track

    def update(self, pk, data):
        track = self._track(pk, name=data["name"], is_public=data["is_public"])
        self.rows[pk] = (track, data["space_pks"], data["manager_pks"])

    def delete(self, pk):
        del self.rows[pk]

    def read_by_slug(self, event_pk, slug):
        del event_pk
        for track, _spaces, _managers in self.rows.values():
            if track.slug == slug:
                return track
        raise NotFoundError

    def find_by_event_and_name(self, event_pk, name):
        del event_pk
        return next(
            (track for track, _s, _m in self.rows.values() if track.name == name), None
        )

    def list_space_pks(self, pk):
        return self.rows[pk][1]

    def list_manager_pks(self, pk):
        return self.rows[pk][2]

    def list_space_pks_by_event(self, event_pk):
        del event_pk
        return {pk: spaces for pk, (_t, spaces, _m) in self.rows.items()}

    def list_by_event_with_assignments(self, event_pk):
        del event_pk
        return [
            TrackListItemDTO(
                pk=track.pk,
                name=track.name,
                slug=track.slug,
                is_public=track.is_public,
                space_names=[_space(pk).name for pk in spaces],
                manager_names=[_user(pk).username for pk in managers],
            )
            for track, spaces, managers in self.rows.values()
        ]


def _service(tracks, *, space_pks=(1, 2), manager_pks=(7, 8)):
    return TracksPanelService(
        transaction=FakeTransaction(),
        tracks=tracks,
        spaces=FakeSpaces(space_pks),
        spheres=FakeSpheres(manager_pks),
    )


def _form(*, name="Alpha", is_public=True, space_pks=(2, 1), manager_pks=(8,)):
    return TrackFormData(
        name=name,
        is_public=is_public,
        space_pks=list(space_pks),
        manager_pks=list(manager_pks),
    )


class TestTracksPanelServiceOutcomes:
    def test_create_stores_the_scoped_selection_sorted(self):
        tracks = FakeTracks()

        created = _service(tracks).create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        assert created.name == "Alpha"
        assert tracks.rows[created.pk] == (created, [1, 2], [8])

    def test_create_refuses_a_manager_from_another_sphere(self):
        tracks = FakeTracks()

        with pytest.raises(TrackSelectionInvalidError):
            _service(tracks).create(
                event_pk=EVENT_PK, sphere_id=3, data=_form(manager_pks=(99,))
            )

        assert not tracks.rows

    def test_find_or_create_returns_the_track_already_carrying_the_name(self):
        tracks = FakeTracks()
        service = _service(tracks)
        existing = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        found = service.find_or_create(
            event_pk=EVENT_PK, sphere_id=3, data=_form(space_pks=(1,))
        )

        assert found == existing
        assert tracks.rows[existing.pk][1] == [1, 2]

    def test_update_replaces_name_flag_and_assignments(self):
        tracks = FakeTracks()
        service = _service(tracks)
        track = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        service.update(
            event_pk=EVENT_PK,
            sphere_id=3,
            track_slug=track.slug,
            data=_form(name="Beta", is_public=False, space_pks=(1,), manager_pks=()),
        )

        updated, spaces, managers = tracks.rows[track.pk]
        assert (updated.name, updated.is_public) == ("Beta", False)
        assert (spaces, managers) == ([1], [])

    def test_update_of_a_foreign_slug_raises_without_side_effects(self):
        tracks = FakeTracks()
        service = _service(tracks)
        track = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        with pytest.raises(NotFoundError):
            service.update(
                event_pk=EVENT_PK,
                sphere_id=3,
                track_slug="foreign",
                data=_form(name="Beta"),
            )

        assert tracks.rows[track.pk][0] == track

    def test_delete_removes_the_track(self):
        tracks = FakeTracks()
        service = _service(tracks)
        track = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        service.delete(event_pk=EVENT_PK, track_slug=track.slug)

        assert not tracks.rows

    def test_list_reads_expose_assignments_by_name_and_by_pk(self):
        tracks = FakeTracks()
        service = _service(tracks)
        track = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        listed = service.list_tracks(EVENT_PK)

        assert [(t.slug, t.space_names, t.manager_names) for t in listed] == [
            ("alpha", ["Sala 1", "Sala 2"], ["user8"])
        ]
        assert service.list_space_pks_by_event(EVENT_PK) == {track.pk: [1, 2]}

    def test_form_contexts_offer_the_event_spaces_and_sphere_managers(self):
        tracks = FakeTracks()
        service = _service(tracks)
        track = service.create(event_pk=EVENT_PK, sphere_id=3, data=_form())

        form = service.get_form_context(event_pk=EVENT_PK, sphere_id=3)
        edit_form = service.get_edit_form_context(
            event_pk=EVENT_PK, sphere_id=3, track_slug=track.slug
        )
        edit = service.get_edit_context(
            event_pk=EVENT_PK, sphere_id=3, track_slug=track.slug
        )

        assert [s.pk for s in form.spaces] == [1, 2]
        assert [m.pk for m in form.managers] == [7, 8]
        assert (edit_form.spaces, edit_form.managers) == (form.spaces, form.managers)
        assert edit_form.track == track
        assert (edit.selected_space_pks, edit.selected_manager_pks) == ([1, 2], [8])
