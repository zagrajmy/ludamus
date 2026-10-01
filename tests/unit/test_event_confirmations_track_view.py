from datetime import UTC, datetime

import pytest

from ludamus.mills.event import EventConfirmationsService
from ludamus.pacts.event import ConfirmationSessionDTO
from ludamus.pacts.legacy import (
    ConfirmationFacilitatorRow,
    ConfirmationSessionRow,
    FacilitatorDTO,
    NotFoundError,
    SessionStatus,
    TrackDTO,
)
from ludamus.specs.confirmations import SCHEDULED_STATUS

_EVENT = 1
_OTHER_EVENT = 2
_ADA = 11
_BEN = 12
_RPG_TRACK = 21
_TALKS_TRACK = 22
_FOREIGN_TRACK = 23
_ITEM = 100
_ORGANIZER = 5
_ORPHANS = 3
_EXPECTED_TWO = 2
_FULL = 100
_NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _facilitator(
    *, pk: int = _ADA, name: str = "Ada", organizer_id: int | None = None
) -> ConfirmationFacilitatorRow:
    return ConfirmationFacilitatorRow(
        pk=pk,
        display_name=name,
        slug=name.lower(),
        organizer_id=organizer_id,
        organizer_name="Radek" if organizer_id else "",
    )


def _session(
    *,
    session_pk: int,
    facilitator_pk: int = _ADA,
    title: str = "Dragons",
    is_confirmed: bool = False,
    status: SessionStatus = SessionStatus.ACCEPTED,
    contact_email: str = "ada@example.com",
    agenda_item_pk: int | None = _ITEM,
) -> ConfirmationSessionRow:
    return ConfirmationSessionRow(
        facilitator_pk=facilitator_pk,
        session_pk=session_pk,
        title=title,
        status=status,
        contact_email=contact_email,
        category_name="RPG session",
        agenda_item_pk=agenda_item_pk,
        is_confirmed=is_confirmed,
        start_time=datetime(2026, 8, 1, 10, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 12, tzinfo=UTC),
        room_name="Room 3",
    )


def _facilitator_dto(row: ConfirmationFacilitatorRow, event_id: int) -> FacilitatorDTO:
    return FacilitatorDTO(
        accreditation_type="",
        display_name=row["display_name"],
        event_id=event_id,
        organizer_id=row["organizer_id"],
        organizer_name=row["organizer_name"] or None,
        pk=row["pk"],
        slug=row["slug"],
        user_id=None,
    )


class FakeFacilitators:
    def __init__(
        self, rows: list[ConfirmationFacilitatorRow], *, event_id: int = _EVENT
    ) -> None:
        self._rows = rows
        self._event_id = event_id
        self._in_track = {(event_id, _RPG_TRACK): rows}

    def list_with_scheduled_session_in_track(
        self, event_pk: int, track_pk: int
    ) -> list[ConfirmationFacilitatorRow]:
        return self._in_track[event_pk, track_pk]

    def read(self, pk: int) -> FacilitatorDTO:
        row = next(row for row in self._rows if row["pk"] == pk)
        return _facilitator_dto(row, self._event_id)


class FakeAgendaCounts:
    def __init__(self, *, matched: int = 1, orphans: int = 0) -> None:
        self._matched = matched
        self._orphans = {(_EVENT, _RPG_TRACK): orphans}
        self.confirmed: list[tuple[int, int, bool, str | None, int | None]] = []

    def count_without_facilitator(self, event_pk: int, track_pk: int) -> int:
        return self._orphans[event_pk, track_pk]

    def set_confirmed_for_facilitator(
        self,
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None,
        agenda_item_pk: int | None,
    ) -> int:
        self.confirmed.append(
            (event_pk, facilitator_pk, confirmed, contact_email, agenda_item_pk)
        )
        return self._matched


class FakeTracks:
    def __init__(self, event_by_track: dict[int, int]) -> None:
        self._event_by_track = event_by_track

    def read(self, pk: int) -> TrackDTO:
        return TrackDTO(
            creation_time=_NOW,
            event_id=self._event_by_track[pk],
            is_public=True,
            modification_time=_NOW,
            name="Block",
            pk=pk,
            slug="block",
        )


class FakeSessions:
    def __init__(
        self,
        rows: list[ConfirmationSessionRow],
        track_names: dict[int, dict[int, str]] | None = None,
        facilitator_names: dict[int, dict[int, str]] | None = None,
    ) -> None:
        self._rows = {_EVENT: rows}
        self._track_names = track_names or {}
        self._facilitator_names = facilitator_names or {}
        self.queried_pks: list[list[int]] = []
        self.queried_session_pks: list[list[int]] = []

    def list_confirmation_rows(
        self, event_pk: int, facilitator_pks: list[int]
    ) -> list[ConfirmationSessionRow]:
        self.queried_pks.append(facilitator_pks)
        return [
            row
            for row in self._rows[event_pk]
            if row["facilitator_pk"] in facilitator_pks
        ]

    def list_track_names_by_session(
        self, session_pks: list[int]
    ) -> dict[int, dict[int, str]]:
        self.queried_session_pks.append(session_pks)
        return {
            pk: self._track_names[pk] for pk in session_pks if pk in self._track_names
        }

    def list_facilitator_names_by_session(
        self, session_pks: list[int]
    ) -> dict[int, dict[int, str]]:
        self.queried_session_pks.append(session_pks)
        return {
            pk: self._facilitator_names[pk]
            for pk in session_pks
            if pk in self._facilitator_names
        }


def _service(
    *,
    facilitators: list[ConfirmationFacilitatorRow] | None = None,
    sessions: list[ConfirmationSessionRow] | None = None,
    track_names: dict[int, dict[int, str]] | None = None,
    facilitator_names: dict[int, dict[int, str]] | None = None,
    facilitator_event: int = _EVENT,
    agenda_items: FakeAgendaCounts | None = None,
) -> EventConfirmationsService:
    return EventConfirmationsService(
        facilitators=FakeFacilitators(
            facilitators if facilitators is not None else [_facilitator()],
            event_id=facilitator_event,
        ),
        agenda_items=agenda_items or FakeAgendaCounts(),
        tracks=FakeTracks({_RPG_TRACK: _EVENT, _FOREIGN_TRACK: _OTHER_EVENT}),
        sessions=FakeSessions(sessions or [], track_names, facilitator_names),
    )


class TestTrackView:
    def test_other_track_is_labelled_and_left_out_of_the_track_counters(self):
        service = _service(
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, title="Talk"),
            ],
            track_names={1: {_RPG_TRACK: "RPG"}, 2: {_TALKS_TRACK: "Talks"}},
        )

        view = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK)

        sessions = view.facilitators[0].email_groups[0].status_groups[0].sessions
        assert sessions[0].other_track_names == []
        assert sessions[1].other_track_names == ["Talks"]
        # The strip counts the block; the card counts the whole event.
        assert view.scheduled_count == 1
        assert view.confirmed_count == 1
        assert view.progress_pct == _FULL
        assert view.facilitators[0].scheduled_count == _EXPECTED_TWO
        assert view.facilitators[0].confirmed_count == 1

    def test_fully_confirmed_facilitators_sort_below_unfinished_ones(self):
        service = _service(
            facilitators=[
                _facilitator(pk=_ADA, name="Ada"),
                _facilitator(pk=_BEN, name="Ben"),
            ],
            sessions=[
                _session(session_pk=1, facilitator_pk=_ADA, is_confirmed=True),
                _session(session_pk=2, facilitator_pk=_BEN, is_confirmed=False),
            ],
        )

        view = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK)

        assert [f.display_name for f in view.facilitators] == ["Ben", "Ada"]
        assert view.facilitators[1].is_fully_confirmed

    def test_an_empty_block_is_an_empty_view_without_session_queries(self):
        sessions = FakeSessions([])
        service = EventConfirmationsService(
            facilitators=FakeFacilitators([]),
            agenda_items=FakeAgendaCounts(orphans=_ORPHANS),
            tracks=FakeTracks({}),
            sessions=sessions,
        )

        view = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK)

        assert view.facilitators == []
        assert view.progress_pct == 0
        assert view.without_facilitator_count == _ORPHANS
        assert not sessions.queried_pks
        assert not sessions.queried_session_pks

    def test_a_facilitator_with_no_sessions_is_listed_as_unfinished(self):
        sessions = FakeSessions([])
        service = EventConfirmationsService(
            facilitators=FakeFacilitators([_facilitator()]),
            agenda_items=FakeAgendaCounts(),
            tracks=FakeTracks({}),
            sessions=sessions,
        )

        view = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK)

        card = view.facilitators[0]
        assert card.email_groups == []
        assert card.is_fully_confirmed is False
        assert view.unclaimed_facilitator_count == 1
        assert sessions.queried_pks == [[_ADA]]
        assert not sessions.queried_session_pks

    def test_unplaced_sessions_are_counted_not_listed(self):
        service = _service(
            sessions=[
                _session(session_pk=1),
                _session(session_pk=2, agenda_item_pk=None),
                _session(
                    session_pk=3, agenda_item_pk=None, status=SessionStatus.PENDING
                ),
                _session(
                    session_pk=4, agenda_item_pk=None, status=SessionStatus.ON_HOLD
                ),
                _session(
                    session_pk=5, agenda_item_pk=None, status=SessionStatus.REJECTED
                ),
                _session(session_pk=6, agenda_item_pk=None),
            ]
        )

        card = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK).facilitators[0]

        assert card.unplaced_count == _EXPECTED_TWO
        assert card.pending_count == 1
        groups = card.email_groups[0].status_groups
        assert [group.status for group in groups] == [
            SCHEDULED_STATUS,
            str(SessionStatus.ON_HOLD),
            str(SessionStatus.REJECTED),
        ]
        assert [[s.session_pk for s in g.sessions] for g in groups] == [[1], [4], [5]]
        assert card.email_groups[0].confirmable_count == 1

    def test_an_address_less_group_sorts_last(self):
        service = _service(
            sessions=[
                _session(session_pk=1, contact_email=""),
                _session(session_pk=2, contact_email="zed@example.com"),
                _session(session_pk=3, contact_email="ada@example.com"),
            ]
        )

        card = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK).facilitators[0]

        assert [g.contact_email for g in card.email_groups] == [
            "ada@example.com",
            "zed@example.com",
            "",
        ]

    def test_co_facilitators_exclude_the_card_owner(self):
        service = _service(
            sessions=[_session(session_pk=1)],
            facilitator_names={1: {_ADA: "Ada", _BEN: "Ben"}},
        )

        card = service.track_view(event_pk=_EVENT, track_pk=_RPG_TRACK).facilitators[0]

        session = card.email_groups[0].status_groups[0].sessions[0]
        assert session.co_facilitator_names == ["Ben"]


class TestFacilitatorCard:
    def test_returns_the_facilitator_with_every_session_in_the_event(self):
        service = _service(
            facilitators=[
                _facilitator(pk=_ADA, organizer_id=_ORGANIZER),
                _facilitator(pk=_BEN),
            ],
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, facilitator_pk=_BEN),
            ],
            track_names={1: {_RPG_TRACK: "RPG", _TALKS_TRACK: "Talks"}},
            facilitator_names={1: {_ADA: "Ada", _BEN: "Ben"}},
        )

        card = service.facilitator_card(
            event_pk=_EVENT, track_pk=_RPG_TRACK, facilitator_pk=_ADA
        )

        assert card.pk == _ADA
        assert card.organizer_id == _ORGANIZER
        assert card.organizer_name == "Radek"
        assert card.scheduled_count == 1
        assert card.is_fully_confirmed is True
        assert card.email_groups[0].status_groups[0].sessions == [
            ConfirmationSessionDTO(
                session_pk=1,
                title="Dragons",
                category_name="RPG session",
                room_name="Room 3",
                start_time=datetime(2026, 8, 1, 10, tzinfo=UTC),
                end_time=datetime(2026, 8, 1, 12, tzinfo=UTC),
                agenda_item_pk=_ITEM,
                is_confirmed=True,
                co_facilitator_names=["Ben"],
                other_track_names=["Talks"],
            )
        ]

    def test_an_unclaimed_facilitator_has_no_organizer(self):
        service = _service()

        card = service.facilitator_card(
            event_pk=_EVENT, track_pk=_RPG_TRACK, facilitator_pk=_ADA
        )

        assert card.organizer_id is None
        assert not card.organizer_name

    def test_a_facilitator_of_another_event_is_not_found(self):
        service = _service(facilitator_event=_OTHER_EVENT)

        with pytest.raises(NotFoundError):
            service.facilitator_card(
                event_pk=_EVENT, track_pk=_RPG_TRACK, facilitator_pk=_ADA
            )

    def test_a_track_of_another_event_is_not_found(self):
        service = _service()

        with pytest.raises(NotFoundError):
            service.facilitator_card(
                event_pk=_EVENT, track_pk=_FOREIGN_TRACK, facilitator_pk=_ADA
            )


class TestSetConfirmed:
    def test_writes_the_flag_for_the_facilitator_scope(self):
        agenda_items = FakeAgendaCounts(matched=0)
        service = _service(agenda_items=agenda_items)

        service.set_confirmed(
            event_pk=_EVENT,
            facilitator_pk=_ADA,
            confirmed=True,
            contact_email="ada@example.com",
        )

        assert agenda_items.confirmed == [(_EVENT, _ADA, True, "ada@example.com", None)]

    def test_one_item_that_matches_nothing_is_not_found(self):
        agenda_items = FakeAgendaCounts(matched=0)
        service = _service(agenda_items=agenda_items)

        with pytest.raises(NotFoundError):
            service.set_confirmed(
                event_pk=_EVENT,
                facilitator_pk=_ADA,
                confirmed=False,
                agenda_item_pk=_ITEM,
            )

    def test_one_item_that_matches_is_written(self):
        agenda_items = FakeAgendaCounts(matched=1)
        service = _service(agenda_items=agenda_items)

        service.set_confirmed(
            event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True, agenda_item_pk=_ITEM
        )

        assert agenda_items.confirmed == [(_EVENT, _ADA, True, None, _ITEM)]

    def test_a_facilitator_of_another_event_is_never_written(self):
        agenda_items = FakeAgendaCounts()
        service = _service(facilitator_event=_OTHER_EVENT, agenda_items=agenda_items)

        with pytest.raises(NotFoundError):
            service.set_confirmed(event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True)

        assert not agenda_items.confirmed
