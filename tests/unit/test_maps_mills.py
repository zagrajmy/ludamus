from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ludamus.mills.maps import EventMapsService
from ludamus.pacts import NotFoundError, SpaceDTO
from ludamus.pacts.maps import (
    EventMapDTO,
    EventMapPageDTO,
    EventMapRecordDTO,
    MapTreeNodeDTO,
)
from tests.unit.factories import FakeTransaction

EVENT_PK = 7
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


def _page(pk, image_url=None):
    return EventMapPageDTO(pk=pk, image_url=image_url or f"/media/eventmaps/{pk}.png")


def _record(pk, space_pks, *, event_id=EVENT_PK, name=None):
    return EventMapRecordDTO(
        pk=pk,
        event_id=event_id,
        name=name or f"map-{pk}",
        pages=[_page(pk)],
        space_pks=list(space_pks),
    )


def _upload(name):
    return SimpleNamespace(name=name, read=lambda _size=-1: b"")


class FakeMaps:
    def __init__(self, records=()):
        self.rows = {record.pk: record for record in records}

    def list_for_event(self, event_pk):
        return [row for row in self.rows.values() if row.event_id == event_pk]

    def exists_for_event(self, event_pk):
        return any(row.event_id == event_pk for row in self.rows.values())

    def read(self, pk):
        return self.rows[pk]

    def create(self, *, event_pk, name, images):
        pk = max(self.rows, default=0) + 1
        self.rows[pk] = EventMapRecordDTO(
            pk=pk,
            event_id=event_pk,
            name=name,
            pages=[_page(pk, image.name) for image in images],
        )
        return self.rows[pk]

    def update(self, *, pk, name, images):
        pages = (
            self.rows[pk].pages
            if images is None
            else [_page(pk, image.name) for image in images]
        )
        self.rows[pk] = self.rows[pk].model_copy(update={"name": name, "pages": pages})
        return self.rows[pk]

    def set_spaces(self, pk, space_pks):
        self.rows[pk] = self.rows[pk].model_copy(update={"space_pks": list(space_pks)})

    def delete(self, pk):
        del self.rows[pk]


class FakeSpaces:
    def __init__(self, spaces=()):
        self.by_event = {EVENT_PK: list(spaces)}

    def list_by_event(self, event_pk):
        return self.by_event.get(event_pk, [])


def _service(*, maps=(), spaces=()):
    maps_repo = FakeMaps(maps)
    return EventMapsService(FakeTransaction(), maps_repo, FakeSpaces(spaces)), maps_repo


class TestListForEvent:
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
                pages=[EventMapPageDTO(pk=10, image_url="/media/eventmaps/10.png")],
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

    def test_a_room_whose_parent_the_event_does_not_list_is_not_drawn(self):
        service, _maps = _service(
            maps=[_record(10, [2])], spaces=[_space(2, parent_id=99, name="Room")]
        )

        [event_map] = service.list_for_event(EVENT_PK)

        assert event_map.tree == []

    def test_another_events_maps_are_not_listed(self):
        service, _maps = _service(
            maps=[_record(10, [1], event_id=EVENT_PK + 1)], spaces=[_space(1)]
        )

        assert service.list_for_event(EVENT_PK) == []


class TestMapForSpace:
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

    def test_a_space_the_event_does_not_list_resolves_to_nothing(self):
        service, _maps = _service(maps=[_record(10, [1])], spaces=[_space(1)])

        assert service.map_pk_for_space(event_pk=EVENT_PK, space_pk=99) is None

    def test_first_map_in_display_order_wins_for_a_space_on_two_maps(self):
        service, _maps = _service(
            maps=[_record(SITE_PLAN_PK, [1]), _record(FLOOR_PLAN_PK, [1])],
            spaces=[_space(1)],
        )

        assert service.map_pk_for_space(event_pk=EVENT_PK, space_pk=1) == SITE_PLAN_PK


class TestScoping:
    def test_attach_refuses_a_space_of_another_event_without_writing(self):
        service, maps = _service(maps=[_record(10, [])], spaces=[_space(1)])

        with pytest.raises(NotFoundError):
            service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[1, 99])

        assert maps.rows[10].space_pks == []

    def test_read_refuses_a_map_of_another_event(self):
        service, _maps = _service(maps=[_record(10, [], event_id=99)])

        with pytest.raises(NotFoundError):
            service.read(event_pk=EVENT_PK, pk=10)

    def test_read_hands_back_the_events_own_map(self):
        service, _maps = _service(maps=[_record(10, [1])])

        assert service.read(event_pk=EVENT_PK, pk=10) == _record(10, [1])

    def test_update_and_delete_go_through_the_scoped_read(self):
        foreign = _record(10, [], event_id=99)
        service, maps = _service(maps=[foreign])

        with pytest.raises(NotFoundError):
            service.update(event_pk=EVENT_PK, pk=10, name="Site", images=None)
        with pytest.raises(NotFoundError):
            service.delete(event_pk=EVENT_PK, pk=10)

        assert maps.rows == {10: foreign}

    def test_attach_writes_the_events_own_spaces(self):
        service, maps = _service(maps=[_record(10, [])], spaces=[_space(1), _space(2)])

        service.attach_spaces(event_pk=EVENT_PK, pk=10, space_pks=[1, 2])

        assert maps.rows[10] == _record(10, [1, 2])


class TestWrites:
    def test_create_stores_the_map_under_the_event(self):
        service, maps = _service()

        created = service.create(
            event_pk=EVENT_PK, name="Site", images=[_upload("site.png")]
        )

        assert created == EventMapRecordDTO(
            pk=1,
            event_id=EVENT_PK,
            name="Site",
            pages=[EventMapPageDTO(pk=1, image_url="site.png")],
            space_pks=[],
        )
        assert maps.rows == {1: created}

    def test_update_renames_and_keeps_the_pages_without_new_images(self):
        service, maps = _service(maps=[_record(10, [1])])

        updated = service.update(event_pk=EVENT_PK, pk=10, name="Floor", images=None)

        assert updated == _record(10, [1], name="Floor")
        assert maps.rows == {10: updated}

    def test_update_replaces_the_pages_with_the_new_images(self):
        service, _maps = _service(maps=[_record(10, [1])])

        updated = service.update(
            event_pk=EVENT_PK, pk=10, name="Floor", images=[_upload("floor.png")]
        )

        assert updated == _record(10, [1], name="Floor").model_copy(
            update={"pages": [EventMapPageDTO(pk=10, image_url="floor.png")]}
        )

    def test_delete_removes_the_events_map(self):
        service, maps = _service(maps=[_record(10, []), _record(11, [])])

        service.delete(event_pk=EVENT_PK, pk=10)

        assert list(maps.rows) == [11]


class TestEmptyEvent:
    def test_no_maps_means_nothing_to_list_or_resolve(self):
        service, _maps = _service(spaces=[_space(1)])

        assert service.list_for_event(EVENT_PK) == []
        assert service.map_pk_for_space(event_pk=EVENT_PK, space_pk=1) is None
        assert service.has_maps(EVENT_PK) is False

    def test_has_maps_sees_only_the_events_own(self):
        service, _maps = _service(maps=[_record(10, [])])

        assert service.has_maps(EVENT_PK) is True
        assert service.has_maps(EVENT_PK + 1) is False
