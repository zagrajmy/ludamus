from datetime import UTC, datetime

from ludamus.mills.event import EventConfirmationsService
from ludamus.pacts.legacy import (
    ConfirmationFacilitatorRow,
    ConfirmationSessionRow,
    SessionStatus,
)

_ADA = 11
_BEN = 12
_RPG_TRACK = 21
_TALKS_TRACK = 22
_EXPECTED_TWO = 2


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
) -> ConfirmationSessionRow:
    return ConfirmationSessionRow(
        facilitator_pk=facilitator_pk,
        session_pk=session_pk,
        title=title,
        status=SessionStatus.ACCEPTED,
        contact_email="ada@example.com",
        category_name="RPG session",
        agenda_item_pk=100,
        is_confirmed=is_confirmed,
        start_time=datetime(2026, 8, 1, 10, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 12, tzinfo=UTC),
        room_name="Room 3",
    )


class FakeFacilitators:
    def __init__(self, rows: list[ConfirmationFacilitatorRow]) -> None:
        self._rows = rows

    def list_with_scheduled_session_in_track(
        self, _event_pk: int, _track_pk: int
    ) -> list[ConfirmationFacilitatorRow]:
        return self._rows


class FakeAgendaCounts:
    @staticmethod
    def count_without_facilitator(_event_pk: int, _track_pk: int | None = None) -> int:
        return 0


class FakeSessions:
    def __init__(
        self,
        rows: list[ConfirmationSessionRow],
        track_names: dict[int, dict[int, str]] | None = None,
    ) -> None:
        self._rows = rows
        self._track_names = track_names or {}

    def list_confirmation_rows(
        self, _event_pk: int, _facilitator_pks: list[int]
    ) -> list[ConfirmationSessionRow]:
        return self._rows

    def list_track_names_by_session(
        self, _session_pks: list[int]
    ) -> dict[int, dict[int, str]]:
        return self._track_names

    @staticmethod
    def list_facilitator_names_by_session(
        _session_pks: list[int],
    ) -> dict[int, dict[int, str]]:
        return {}


def _service(
    *,
    facilitators: list[ConfirmationFacilitatorRow] | None = None,
    sessions: list[ConfirmationSessionRow] | None = None,
    track_names: dict[int, dict[int, str]] | None = None,
) -> EventConfirmationsService:
    return EventConfirmationsService(
        facilitators=FakeFacilitators(
            facilitators if facilitators is not None else [_facilitator()]
        ),
        agenda_items=FakeAgendaCounts(),
        tracks=None,
        sessions=FakeSessions(sessions or [], track_names),
    )


class TestTrackView:
    def test_other_track_is_labelled_and_left_out_of_the_track_counters(self):
        service = _service(
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

        view = service.track_view(event_pk=1, track_pk=_RPG_TRACK)

        assert [f.display_name for f in view.facilitators] == ["Ben", "Ada"]
        assert view.facilitators[1].is_fully_confirmed
