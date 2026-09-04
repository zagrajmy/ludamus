from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.maps import EventMapsService
from ludamus.pacts import NotFoundError, SpaceDTO
from ludamus.pacts.maps import EventMapDTO, EventMapRecordDTO, MapTreeNodeDTO

EVENT_PK = 7
OTHER_EVENT_PK = 8
SITE_PLAN_PK = 10
FLOOR_PLAN_PK = 20


def _space(pk, parent_id=None, name=None):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SpaceDTO(
        pk=pk,
        parent_id=parent_id,
        capacity=None,
        creation_time=now,
        modification_time=now,
        name=name or f"space-{pk}",
        order=0,
        slug=f"space-{pk}",
    )


def _record(pk, space_pks, event_id=EVENT_PK):
    return EventMapRecordDTO(
        pk=pk,
        event_id=event_id,
        name=f"map-{pk}",
        image_url=f"/media/eventmaps/{pk}.png",
        space_pks=list(space_pks),
    )


def _service(*, maps=(), spaces=()):
    maps_repo = MagicMock()
    maps_repo.list_for_event.return_value = list(maps)
    spaces_repo = MagicMock()
    spaces_repo.list_by_event.return_value = list(spaces)
    return EventMapsService(MagicMock(), maps_repo, spaces_repo), maps_repo


class TestListForEvent:
    def test_no_maps_reads_no_spaces(self):
        service, _maps = _service(spaces=[_space(1)])

        assert service.list_for_event(EVENT_PK) == []

    def test_draws_attached_rooms_under_their_unattached_venue(self):
        # Hall > Room 1, Room 2; only Room 1 is on the map. The hall frames it
        # as plain text, Room 2 is not drawn at all, and a space the event no
        # longer has (99) is dropped.
        service, _maps = _service(
            maps=[_record(10, [2, 99])],
            spaces=[
                _space(1, name="Hall"),
                _space(2, parent_id=1, name="Room 1"),
                _space(3, parent_id=1, name="Room 2"),
            ],
        )

        assert service.list_for_event(EVENT_PK) == [
            EventMapDTO(
                pk=10,
                event_id=EVENT_PK,
                name="map-10",
                image_url="/media/eventmaps/10.png",
                space_pks=[2, 99],
                tree=[
                    MapTreeNodeDTO(
                        pk=1,
                        name="Hall",
                        attached=False,
                        has_children=True,
                        schedule_filter="venue:1",
                        children=[
                            MapTreeNodeDTO(
                                pk=2,
                                name="Room 1",
                                attached=True,
                                has_children=False,
                                schedule_filter="2",
                                children=[],
                            )
                        ],
                    )
                ],
            )
        ]

    def test_a_venue_above_the_rooms_parent_gets_no_schedule_filter(self):
        # Building 1 > Floor 2 > Room 3. The schedule filters by room or by
        # the room's direct parent, so the building node cannot link.
        service, _maps = _service(
            maps=[_record(10, [1])],
            spaces=[_space(1), _space(2, parent_id=1), _space(3, parent_id=2)],
        )

        [event_map] = service.list_for_event(EVENT_PK)

        assert [node.schedule_filter for node in event_map.tree] == [None]
        assert event_map.tree[0].children == []


class TestMapForSpace:
    def test_no_attached_spaces_means_no_map(self):
        service, _maps = _service(maps=[_record(10, [])], spaces=[_space(1)])

        assert service.map_pk_for_space(event_pk=EVENT_PK, space_pk=1) is None

    def test_room_inherits_the_map_of_its_nearest_mapped_ancestor(self):
        # Building 1 > Floor 2 > Room 3; Floor 2 is on map 20, Building 1 on
        # map 10. The room resolves to the floor plan, the building to the
        # site plan, and an unrelated space 4 to nothing.
        service, _maps = _service(
            maps=[_record(10, [1]), _record(20, [2])],
            spaces=[
                _space(1),
                _space(2, parent_id=1),
                _space(3, parent_id=2),
                _space(4),
            ],
        )

        resolved = {
            pk: service.map_pk_for_space(event_pk=EVENT_PK, space_pk=pk)
            for pk in (1, 2, 3, 4)
        }

        assert resolved == {1: 10, 2: 20, 3: 20, 4: None}

    def test_first_map_in_display_order_wins_for_a_space_on_two_maps(self):
        service, _maps = _service(
            maps=[_record(SITE_PLAN_PK, [1]), _record(FLOOR_PLAN_PK, [1])],
            spaces=[_space(1)],
        )

        assert service.map_pk_for_space(event_pk=EVENT_PK, space_pk=1) == SITE_PLAN_PK


class TestScoping:
    def test_read_refuses_a_map_of_another_event(self):
        service, maps = _service()
        maps.read.return_value = _record(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.read(event_pk=EVENT_PK, pk=10)

    def test_attach_refuses_a_space_of_another_event_without_writing(self):
        service, maps = _service(spaces=[_space(1)])
        maps.read.return_value = _record(10, [])

        with pytest.raises(NotFoundError):
            service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[1, 99])

        maps.set_spaces.assert_not_called()

    def test_attach_writes_the_events_own_spaces(self):
        service, maps = _service(spaces=[_space(1), _space(2)])
        maps.read.return_value = _record(10, [])

        service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[2])

        maps.set_spaces.assert_called_once_with(10, [2])

    def test_update_refuses_a_map_of_another_event_without_writing(self):
        service, maps = _service()
        maps.read.return_value = _record(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.update(event_pk=EVENT_PK, pk=10, name="Plan", image=None)

        maps.update.assert_not_called()

    def test_delete_refuses_a_map_of_another_event_without_deleting(self):
        service, maps = _service()
        maps.read.return_value = _record(10, [], event_id=OTHER_EVENT_PK)

        with pytest.raises(NotFoundError):
            service.delete(event_pk=EVENT_PK, pk=10)

        maps.delete.assert_not_called()

    def test_delete_removes_the_events_own_map(self):
        service, maps = _service()
        maps.read.return_value = _record(10, [])

        service.delete(event_pk=EVENT_PK, pk=10)

        maps.delete.assert_called_once_with(10)
