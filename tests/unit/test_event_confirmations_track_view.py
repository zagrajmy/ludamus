from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ludamus.mills.event import EventConfirmationsService
from ludamus.pacts.legacy import (
    ConfirmationFacilitatorRow,
    ConfirmationSessionRow,
    FacilitatorDTO,
    NotFoundError,
    SessionStatus,
)

_ADA = 11
_BEN = 12
_RPG_TRACK = 21
_TALKS_TRACK = 22
_EXPECTED_TWO = 2
_EXPECTED_HALF = 50


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
    status: SessionStatus = SessionStatus.ACCEPTED,
    email: str = "ada@example.com",
    agenda_item_pk: int | None = 100,
    is_confirmed: bool = False,
    hour: int = 10,
) -> ConfirmationSessionRow:
    placed = agenda_item_pk is not None
    return ConfirmationSessionRow(
        facilitator_pk=facilitator_pk,
        session_pk=session_pk,
        title=title,
        status=status,
        contact_email=email,
        category_name="RPG session",
        agenda_item_pk=agenda_item_pk,
        is_confirmed=is_confirmed,
        start_time=datetime(2026, 8, 1, hour, tzinfo=UTC) if placed else None,
        end_time=datetime(2026, 8, 1, hour + 2, tzinfo=UTC) if placed else None,
        room_name="Room 3" if placed else "",
    )


class FakeFacilitators:
    def __init__(self, rows: list[ConfirmationFacilitatorRow]) -> None:
        self._rows = rows
        self.calls: list[tuple[int, int]] = []

    def list_with_scheduled_session_in_track(
        self, event_pk: int, track_pk: int
    ) -> list[ConfirmationFacilitatorRow]:
        self.calls.append((event_pk, track_pk))
        return self._rows


class FakeSessions:
    def __init__(
        self,
        rows: list[ConfirmationSessionRow],
        track_names: dict[int, dict[int, str]] | None = None,
        facilitator_names: dict[int, dict[int, str]] | None = None,
    ) -> None:
        self._rows = rows
        self._track_names = track_names or {}
        self._facilitator_names = facilitator_names or {}
        self.calls: list[str] = []

    def list_confirmation_rows(
        self, event_pk: int, facilitator_pks: list[int]
    ) -> list[ConfirmationSessionRow]:
        self.calls.append(f"rows:{event_pk}:{sorted(facilitator_pks)}")
        return self._rows

    def list_track_names_by_session(
        self, session_pks: list[int]
    ) -> dict[int, dict[int, str]]:
        self.calls.append(f"tracks:{sorted(session_pks)}")
        return self._track_names

    def list_facilitator_names_by_session(
        self, session_pks: list[int]
    ) -> dict[int, dict[int, str]]:
        self.calls.append(f"facilitators:{sorted(session_pks)}")
        return self._facilitator_names


def _service(
    *,
    facilitators: list[ConfirmationFacilitatorRow] | None = None,
    sessions: list[ConfirmationSessionRow] | None = None,
    track_names: dict[int, dict[int, str]] | None = None,
    facilitator_names: dict[int, dict[int, str]] | None = None,
) -> tuple[EventConfirmationsService, FakeFacilitators, FakeSessions]:
    facilitator_repo = FakeFacilitators(
        facilitators if facilitators is not None else [_facilitator()]
    )
    session_repo = FakeSessions(sessions or [], track_names, facilitator_names)
    service = EventConfirmationsService(
        transaction=None,
        facilitators=facilitator_repo,
        agenda_items=None,
        tracks=None,
        sessions=session_repo,
    )
    return service, facilitator_repo, session_repo


_EVENT = 1
_FOREIGN_EVENT = 2


class FakeTransaction:
    def __init__(self) -> None:
        self.entered = 0

    @contextmanager
    def atomic(self):
        self.entered += 1
        yield


class FakeFacilitatorReads:
    def __init__(self, *, event_id: int | None) -> None:
        self._event_id = event_id

    def read(self, pk: int) -> FacilitatorDTO:
        if self._event_id is None:
            raise NotFoundError
        return FacilitatorDTO(
            accreditation_type="speaker",
            display_name="Ada",
            event_id=self._event_id,
            organizer_id=None,
            organizer_name=None,
            pk=pk,
            slug="ada",
            user_id=None,
        )


class FakeAgendaWrites:
    def __init__(self, matched: int = 1) -> None:
        self._matched = matched
        self.calls: list[dict[str, object]] = []

    def set_confirmed_for_facilitator(self, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return self._matched


def _write_service(
    *, event_id: int | None = _EVENT, matched: int = 1
) -> tuple[EventConfirmationsService, FakeAgendaWrites, FakeTransaction]:
    agenda_items = FakeAgendaWrites(matched)
    transaction = FakeTransaction()
    service = EventConfirmationsService(
        transaction=transaction,
        facilitators=FakeFacilitatorReads(event_id=event_id),
        agenda_items=agenda_items,
        tracks=None,
        sessions=None,
    )
    return service, agenda_items, transaction


class TestSetConfirmed:
    def test_writes_the_named_scope_inside_a_transaction(self):
        service, agenda_items, transaction = _write_service()

        service.set_confirmed(
            event_pk=_EVENT,
            facilitator_pk=_ADA,
            confirmed=True,
            contact_email="ada@example.com",
            agenda_item_pk=100,
        )

        assert agenda_items.calls == [
            {
                "event_pk": _EVENT,
                "facilitator_pk": _ADA,
                "confirmed": True,
                "contact_email": "ada@example.com",
                "agenda_item_pk": 100,
            }
        ]
        assert transaction.entered == 1

    def test_refuses_a_facilitator_from_another_event_without_writing(self):
        service, agenda_items, _ = _write_service(event_id=_FOREIGN_EVENT)

        with pytest.raises(NotFoundError):
            service.set_confirmed(event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True)

        assert not agenda_items.calls

    def test_refuses_an_unknown_facilitator_without_writing(self):
        service, agenda_items, _ = _write_service(event_id=None)

        with pytest.raises(NotFoundError):
            service.set_confirmed(event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True)

        assert not agenda_items.calls

    def test_naming_an_item_that_matches_nothing_is_an_error(self):
        service, _, _ = _write_service(matched=0)

        with pytest.raises(NotFoundError):
            service.set_confirmed(
                event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True, agenda_item_pk=100
            )

    def test_a_scope_wide_call_matching_nothing_is_fine(self):
        service, _, _ = _write_service(matched=0)

        service.set_confirmed(event_pk=_EVENT, facilitator_pk=_ADA, confirmed=True)


class TestTrackView:
    def test_no_facilitators_stops_before_reading_sessions(self):
        service, _, sessions = _service(facilitators=[])

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        assert view.facilitators == []
        assert view.scheduled_count == 0
        assert not sessions.calls

    def test_groups_by_contact_email_then_status(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, title="Wizards", hour=14),
                _session(
                    session_pk=3,
                    title="Maybe",
                    status=SessionStatus.ON_HOLD,
                    agenda_item_pk=None,
                ),
                _session(session_pk=4, title="Club night", email="club@example.org"),
            ],
            track_names={1: {_RPG_TRACK: "RPG"}, 2: {_RPG_TRACK: "RPG"}},
        )

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        groups = view.facilitators[0].email_groups
        assert [group.contact_email for group in groups] == [
            "ada@example.com",
            "club@example.org",
        ]
        assert [status.status for status in groups[0].status_groups] == [
            "scheduled",
            "on_hold",
        ]
        assert [s.title for s in groups[0].status_groups[0].sessions] == [
            "Dragons",
            "Wizards",
        ]

    def test_confirmed_and_unconfirmed_share_the_scheduled_group(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, title="Wizards"),
            ]
        )

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        status_groups = view.facilitators[0].email_groups[0].status_groups
        assert len(status_groups) == 1
        assert [s.is_confirmed for s in status_groups[0].sessions] == [True, False]

    def test_unplaced_accepted_and_pending_are_counted_not_listed(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1),
                _session(session_pk=2, title="Later", agenda_item_pk=None),
                _session(
                    session_pk=3,
                    title="Idea",
                    status=SessionStatus.PENDING,
                    agenda_item_pk=None,
                ),
            ]
        )

        facilitator = service.track_view(event_pk=1, track_pk=_RPG_TRACK).facilitators[
            0
        ]

        titles = [
            session.title
            for group in facilitator.email_groups
            for status_group in group.status_groups
            for session in status_group.sessions
        ]
        assert titles == ["Dragons"]
        assert facilitator.unplaced_count == 1
        assert facilitator.pending_count == 1

    def test_on_hold_and_rejected_stay_listed_without_an_agenda_item(self):
        service, _, _ = _service(
            sessions=[
                _session(
                    session_pk=1,
                    title="Maybe",
                    status=SessionStatus.ON_HOLD,
                    agenda_item_pk=None,
                ),
                _session(
                    session_pk=2,
                    title="Old idea",
                    status=SessionStatus.REJECTED,
                    agenda_item_pk=None,
                ),
            ]
        )

        facilitator = service.track_view(event_pk=1, track_pk=_RPG_TRACK).facilitators[
            0
        ]

        groups = facilitator.email_groups[0].status_groups
        assert [group.status for group in groups] == ["on_hold", "rejected"]
        assert all(
            session.agenda_item_pk is None
            for group in groups
            for session in group.sessions
        )
        assert facilitator.email_groups[0].confirmable_count == 0
        assert facilitator.scheduled_count == 0
        assert not facilitator.is_fully_confirmed

    def test_sessions_without_an_address_group_last(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1, email=""),
                _session(session_pk=2, title="Wizards", email="ada@example.com"),
            ]
        )

        groups = (
            service.track_view(event_pk=1, track_pk=_RPG_TRACK)
            .facilitators[0]
            .email_groups
        )

        assert [group.contact_email for group in groups] == ["ada@example.com", ""]

    def test_other_track_is_labelled_and_left_out_of_the_track_counters(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, title="Talk", is_confirmed=True),
            ],
            track_names={1: {_RPG_TRACK: "RPG"}, 2: {_TALKS_TRACK: "Talks"}},
        )

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        sessions = view.facilitators[0].email_groups[0].status_groups[0].sessions
        assert sessions[0].other_track_names == []
        assert sessions[1].other_track_names == ["Talks"]
        # The strip counts the block; the card counts the whole event.
        assert view.scheduled_count == 1
        assert view.confirmed_count == 1
        assert view.facilitators[0].scheduled_count == _EXPECTED_TWO

    def test_co_facilitators_exclude_the_card_owner(self):
        service, _, _ = _service(
            sessions=[_session(session_pk=1)],
            facilitator_names={1: {_ADA: "Ada", _BEN: "Ben"}},
        )

        session = (
            service.track_view(event_pk=1, track_pk=_RPG_TRACK)
            .facilitators[0]
            .email_groups[0]
            .status_groups[0]
            .sessions[0]
        )

        assert session.co_facilitator_names == ["Ben"]

    def test_fully_confirmed_facilitators_sort_below_unfinished_ones(self):
        service, _, _ = _service(
            facilitators=[
                _facilitator(pk=_ADA, name="Ada"),
                _facilitator(pk=_BEN, name="Ben"),
            ],
            sessions=[
                _session(session_pk=1, facilitator_pk=_ADA, is_confirmed=True),
                _session(session_pk=2, facilitator_pk=_BEN, is_confirmed=False),
            ],
        )

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        assert [f.display_name for f in view.facilitators] == ["Ben", "Ada"]
        assert view.facilitators[1].is_fully_confirmed

    def test_progress_counts_the_track_only(self):
        service, _, _ = _service(
            sessions=[
                _session(session_pk=1, is_confirmed=True),
                _session(session_pk=2, title="Wizards"),
            ],
            track_names={1: {_RPG_TRACK: "RPG"}, 2: {_RPG_TRACK: "RPG"}},
        )

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        assert view.progress_pct == _EXPECTED_HALF
        assert view.unclaimed_facilitator_count == 1
