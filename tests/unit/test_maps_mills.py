from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.maps import EventMapsService
from ludamus.pacts import NotFoundError, SpaceDTO
from ludamus.pacts.maps import EventMapDTO, MapIndexDTO, MapSpaceDTO

EVENT_PK = 7
OTHER_EVENT_PK = 8


def _space(pk, parent_id=None):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SpaceDTO(
        pk=pk,
        parent_id=parent_id,
        capacity=None,
        creation_time=now,
        modification_time=now,
        name=f"space-{pk}",
        order=0,
        slug=f"space-{pk}",
    )


def _map(pk, space_pks, event_id=EVENT_PK):
    return EventMapDTO(
        pk=pk,
        event_id=event_id,
        name=f"map-{pk}",
        image_url=f"/media/eventmaps/{pk}.png",
        spaces=[
            MapSpaceDTO(pk=space_pk, name=f"space-{space_pk}") for space_pk in space_pks
        ],
    )


def _service(*, maps=(), spaces=()):
    maps_repo = MagicMock()
    maps_repo.list_for_event.return_value = list(maps)
    spaces_repo = MagicMock()
    spaces_repo.list_by_event.return_value = list(spaces)
    return EventMapsService(MagicMock(), maps_repo, spaces_repo), maps_repo


class TestIndex:
    def test_no_maps_means_no_page_and_no_links(self):
        service, _maps = _service(spaces=[_space(1)])

        assert service.index(EVENT_PK) == MapIndexDTO(
            has_maps=False, map_pk_by_space={}
        )

    def test_room_inherits_the_map_of_its_nearest_mapped_ancestor(self):
        # Building 1 > Floor 2 > Room 3; Floor 2 is on map 20, Building 1 on
        # map 10. Room 3 and Floor 2 resolve to the floor plan, the building
        # itself to the site plan, and an unrelated space 4 to nothing.
        service, _maps = _service(
            maps=[_map(10, [1]), _map(20, [2])],
            spaces=[
                _space(1),
                _space(2, parent_id=1),
                _space(3, parent_id=2),
                _space(4),
            ],
        )

        assert service.index(EVENT_PK) == MapIndexDTO(
            has_maps=True, map_pk_by_space={1: 10, 2: 20, 3: 20}
        )

    def test_first_map_in_display_order_wins_for_a_space_on_two_maps(self):
        service, _maps = _service(
            maps=[_map(10, [1]), _map(20, [1])], spaces=[_space(1)]
        )

        assert service.index(EVENT_PK).map_pk_by_space == {1: 10}


class TestScoping:
    def test_read_refuses_a_map_of_another_event(self):
        service, maps = _service()
        maps.read.return_value = _map(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.read(event_pk=EVENT_PK, pk=10)

    def test_attach_refuses_a_space_of_another_event_without_writing(self):
        service, maps = _service(spaces=[_space(1)])
        maps.read.return_value = _map(10, [])

        with pytest.raises(NotFoundError):
            service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[1, 99])

        maps.set_spaces.assert_not_called()

    def test_attach_writes_the_events_own_spaces(self):
        service, maps = _service(spaces=[_space(1), _space(2)])
        maps.read.return_value = _map(10, [])

        service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[2])

        maps.set_spaces.assert_called_once_with(10, [2])

    def test_update_refuses_a_map_of_another_event_without_writing(self):
        service, maps = _service()
        maps.read.return_value = _map(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.update(event_pk=EVENT_PK, pk=10, name="Plan", image=None)

        maps.update.assert_not_called()

    def test_delete_refuses_a_map_of_another_event_without_deleting(self):
        service, maps = _service()
        maps.read.return_value = _map(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.delete(event_pk=EVENT_PK, pk=10)

        maps.delete.assert_not_called()

    def test_delete_removes_the_events_own_map(self):
        service, maps = _service()
        maps.read.return_value = _map(10, [])

        service.delete(event_pk=EVENT_PK, pk=10)

        maps.delete.assert_called_once_with(10)
