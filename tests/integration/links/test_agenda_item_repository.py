from datetime import UTC, datetime, timedelta

import pytest

from ludamus.adapters.db.django.models import AgendaItem, Track
from ludamus.links.db.django.agenda_item import AgendaItemRepository
from ludamus.pacts import (
    AgendaItemData,
    AgendaItemUpdateData,
    NotFoundError,
    SessionStatus,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    VenueFactory,
)


class TestAgendaItemRepositoryCreate:
    def test_creates_agenda_item(self, session, space):
        now = datetime.now(UTC)
        data = AgendaItemData(
            end_time=now + timedelta(hours=2),
            session_confirmed=True,
            session_id=session.pk,
            space_id=space.pk,
            start_time=now,
        )

        AgendaItemRepository.create(data)

        assert AgendaItem.objects.filter(session_id=session.pk).exists()


class TestAgendaItemRepositoryRead:
    def test_read_returns_dto(self, agenda_item, session, space):
        dto = AgendaItemRepository.read(agenda_item.pk)

        assert dto.pk == agenda_item.pk
        assert dto.session_id == session.pk
        assert dto.space_id == space.pk
        assert dto.session_confirmed == agenda_item.session_confirmed
        assert dto.start_time == agenda_item.start_time
        assert dto.end_time == agenda_item.end_time
        assert dto.session_title == session.title
        assert dto.presenter_name == session.display_name
        assert dto.session_status == SessionStatus(session.status)

    def test_read_populates_duration_minutes(self, agenda_item):
        dto = AgendaItemRepository.read(agenda_item.pk)

        expected_minutes = int(
            (agenda_item.end_time - agenda_item.start_time).total_seconds() / 60
        )
        assert dto.session_duration_minutes == expected_minutes

    def test_read_populates_category_name(
        self, agenda_item, proposal_category, session
    ):
        session.category = proposal_category
        session.save()

        dto = AgendaItemRepository.read(agenda_item.pk)

        assert dto.category_name == proposal_category.name

    def test_read_category_name_none_when_no_category(self, session, space):
        session.category = None
        session.save()
        item = AgendaItemFactory(session=session, space=space)

        dto = AgendaItemRepository.read(item.pk)

        assert dto.category_name is None

    def test_read_raises_not_found_for_missing_pk(self):
        with pytest.raises(NotFoundError):
            AgendaItemRepository.read(99999)


class TestAgendaItemRepositoryListByEvent:
    def test_list_by_event_returns_items_for_event(self, agenda_item, event):
        result = AgendaItemRepository.list_by_event(event.pk)

        assert len(result) == 1
        assert result[0].pk == agenda_item.pk

    def test_list_by_event_excludes_other_events(self, agenda_item, sphere):
        other_event = EventFactory(sphere=sphere)
        other_venue = VenueFactory(event=other_event)
        other_area = AreaFactory(venue=other_venue)
        other_space = SpaceFactory(area=other_area)
        other_session = SessionFactory(event=other_event)
        AgendaItemFactory(session=other_session, space=other_space)

        result = AgendaItemRepository.list_by_event(other_event.pk)

        assert len(result) == 1
        pks = [dto.pk for dto in result]
        assert agenda_item.pk not in pks

    def test_list_by_event_empty_when_no_items(self, event):
        result = AgendaItemRepository.list_by_event(event.pk)

        assert result == []


class TestAgendaItemRepositoryListBySpace:
    def test_list_by_space_returns_items_for_space(self, agenda_item, space):
        result = AgendaItemRepository.list_by_space(space.pk)

        assert len(result) == 1
        assert result[0].pk == agenda_item.pk
        assert result[0].space_id == space.pk

    def test_list_by_space_excludes_other_spaces(self, agenda_item, area):
        other_space = SpaceFactory(area=area)
        other_session = SessionFactory(event=area.venue.event)
        other_item = AgendaItemFactory(session=other_session, space=other_space)

        result = AgendaItemRepository.list_by_space(agenda_item.space_id)

        result_pks = [dto.pk for dto in result]
        assert agenda_item.pk in result_pks
        assert other_item.pk not in result_pks

    def test_list_by_space_empty_when_no_items(self, space):
        result = AgendaItemRepository.list_by_space(space.pk)

        assert result == []


class TestAgendaItemRepositoryListByTrack:
    def test_list_by_track_returns_items_for_track(self, agenda_item, event, session):
        track = Track.objects.create(
            event=event, name="Test Track", slug="test-track", is_public=True
        )
        session.tracks.add(track)

        result = AgendaItemRepository.list_by_track(track.pk)

        assert len(result) == 1
        assert result[0].pk == agenda_item.pk

    def test_list_by_track_excludes_other_tracks(self, agenda_item, event):
        other_track = Track.objects.create(
            event=event, name="Other Track", slug="other-track", is_public=True
        )

        result = AgendaItemRepository.list_by_track(other_track.pk)

        result_pks = [dto.pk for dto in result]
        assert agenda_item.pk not in result_pks


class TestAgendaItemRepositoryUpdate:
    def test_update_changes_space(self, agenda_item, area):
        new_space = SpaceFactory(area=area)
        data = AgendaItemUpdateData(space_id=new_space.pk)

        AgendaItemRepository.update(agenda_item.pk, data)

        agenda_item.refresh_from_db()
        assert agenda_item.space_id == new_space.pk

    def test_update_changes_times(self, agenda_item):
        now = datetime.now(UTC)
        new_start = now + timedelta(hours=5)
        new_end = now + timedelta(hours=7)
        data = AgendaItemUpdateData(start_time=new_start, end_time=new_end)

        AgendaItemRepository.update(agenda_item.pk, data)

        agenda_item.refresh_from_db()
        assert agenda_item.start_time == new_start
        assert agenda_item.end_time == new_end


class TestAgendaItemRepositoryConfirmAllByEvent:
    def test_confirms_items_in_event(self, agenda_item, event):
        AgendaItemRepository.confirm_all_by_event(event.pk)

        agenda_item.refresh_from_db()
        assert agenda_item.session_confirmed is True

    def test_does_not_touch_other_events(self, agenda_item, sphere):
        other_event = EventFactory(sphere=sphere)
        other_space = SpaceFactory(
            area=AreaFactory(venue=VenueFactory(event=other_event))
        )
        other_item = AgendaItemFactory(
            session=SessionFactory(event=other_event), space=other_space
        )

        AgendaItemRepository.confirm_all_by_event(other_event.pk)

        agenda_item.refresh_from_db()
        other_item.refresh_from_db()
        assert agenda_item.session_confirmed is False
        assert other_item.session_confirmed is True


class TestAgendaItemRepositoryConfirmAllByTrack:
    def test_confirms_only_items_in_track(self, agenda_item, event, session):
        track = Track.objects.create(
            event=event, name="Track", slug="track", is_public=True
        )
        session.tracks.add(track)
        out_space = SpaceFactory(area=AreaFactory(venue=VenueFactory(event=event)))
        out_item = AgendaItemFactory(
            session=SessionFactory(event=event), space=out_space
        )

        AgendaItemRepository.confirm_all_by_track(track.pk)

        agenda_item.refresh_from_db()
        out_item.refresh_from_db()
        assert agenda_item.session_confirmed is True
        assert out_item.session_confirmed is False


class TestAgendaItemRepositoryDelete:
    def test_delete_removes_item(self, agenda_item):
        pk = agenda_item.pk

        AgendaItemRepository.delete(pk)

        assert not AgendaItem.objects.filter(pk=pk).exists()

    def test_delete_nonexistent_does_not_raise(self):
        AgendaItemRepository.delete(99999)
