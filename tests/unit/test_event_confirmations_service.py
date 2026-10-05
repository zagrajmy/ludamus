from ludamus.mills.event import EventConfirmationsService
from ludamus.pacts.event import ConfirmationOrganizerRowDTO
from ludamus.pacts.legacy import ConfirmationCountsRow, ConfirmationTotalsRow

_EVENT = 1
_ADA = 11
_BEN = 12

_EVENT_SCHEDULED = 11
_EVENT_CONFIRMED = 7
_EVENT_PCT = 64
_ADA_PCT = 75
_BEN_PCT = 25
_UNCLAIMED_FACILITATORS = 5
_CLAIMED_FACILITATORS = 3
_RPG_TRACK = 21
_ORPHANS = 4
_HALF = 50


def _row(
    *, key: int | None, name: str, facilitators: int, scheduled: int, confirmed: int
) -> ConfirmationCountsRow:
    return ConfirmationCountsRow(
        key=key,
        name=name,
        facilitator_count=facilitators,
        scheduled_count=scheduled,
        confirmed_count=confirmed,
    )


class FakeFacilitators:
    def __init__(self, rows: list[ConfirmationCountsRow]) -> None:
        self._rows = {_EVENT: rows}

    def count_confirmations_by_organizer(
        self, event_pk: int
    ) -> list[ConfirmationCountsRow]:
        return self._rows[event_pk]


class FakeAgendaItems:
    def __init__(
        self,
        *,
        rows: list[ConfirmationCountsRow],
        without_facilitator: int = 0,
        totals: ConfirmationTotalsRow | None = None,
    ) -> None:
        self._rows = {_EVENT: rows}
        self._without_facilitator = {_EVENT: without_facilitator}
        self._totals = {
            _EVENT: (
                totals or ConfirmationTotalsRow(scheduled_count=0, confirmed_count=0)
            )
        }

    def count_confirmations_by_track(
        self, event_pk: int
    ) -> list[ConfirmationCountsRow]:
        return self._rows[event_pk]

    def count_without_facilitator(self, event_pk: int) -> int:
        return self._without_facilitator[event_pk]

    def count_event_totals(self, event_pk: int) -> ConfirmationTotalsRow:
        return self._totals[event_pk]


class FakeTracks:
    def __init__(self, names: dict[int, list[str]]) -> None:
        self._names = {_EVENT: names}

    def list_manager_names_by_event(self, event_pk: int) -> dict[int, list[str]]:
        return self._names[event_pk]


def _service(
    *,
    organizer_rows: list[ConfirmationCountsRow],
    totals: ConfirmationTotalsRow | None = None,
) -> EventConfirmationsService:
    return EventConfirmationsService(
        facilitators=FakeFacilitators(organizer_rows),
        agenda_items=FakeAgendaItems(rows=[], totals=totals),
        tracks=FakeTracks({}),
        sessions=None,
    )


class TestDashboard:
    def test_totals_come_from_the_items_not_from_the_organizer_rows(self):
        # The rows add up to 12 because one item is run by two facilitators
        # claimed by different organizers. The event has 11.
        service = _service(
            organizer_rows=[
                _row(key=_ADA, name="Ada", facilitators=3, scheduled=8, confirmed=6),
                _row(key=_BEN, name="Ben", facilitators=2, scheduled=4, confirmed=1),
            ],
            totals=ConfirmationTotalsRow(
                scheduled_count=_EVENT_SCHEDULED, confirmed_count=_EVENT_CONFIRMED
            ),
        )

        dashboard = service.dashboard(_EVENT)

        assert dashboard.scheduled_count == _EVENT_SCHEDULED
        assert dashboard.confirmed_count == _EVENT_CONFIRMED
        assert dashboard.progress_pct == _EVENT_PCT
        assert dashboard.organizers == [
            ConfirmationOrganizerRowDTO(
                organizer_id=_ADA,
                organizer_name="Ada",
                facilitator_count=3,
                scheduled_count=8,
                confirmed_count=6,
                progress_pct=_ADA_PCT,
            ),
            ConfirmationOrganizerRowDTO(
                organizer_id=_BEN,
                organizer_name="Ben",
                facilitator_count=2,
                scheduled_count=4,
                confirmed_count=1,
                progress_pct=_BEN_PCT,
            ),
        ]

    def test_unclaimed_row_counts_apart_from_claimed(self):
        service = _service(
            organizer_rows=[
                _row(key=None, name="", facilitators=5, scheduled=9, confirmed=0),
                _row(key=_ADA, name="Ada", facilitators=3, scheduled=8, confirmed=6),
            ]
        )

        dashboard = service.dashboard(_EVENT)

        assert dashboard.unclaimed_facilitator_count == _UNCLAIMED_FACILITATORS
        assert dashboard.claimed_facilitator_count == _CLAIMED_FACILITATORS
        assert dashboard.organizers[0].organizer_id is None
        assert not dashboard.organizers[0].organizer_name

    def test_progress_is_zero_when_nothing_is_scheduled(self):
        service = _service(
            organizer_rows=[
                _row(key=_ADA, name="Ada", facilitators=2, scheduled=0, confirmed=0)
            ],
            totals=ConfirmationTotalsRow(scheduled_count=0, confirmed_count=0),
        )

        dashboard = service.dashboard(_EVENT)

        assert dashboard.progress_pct == 0
        assert dashboard.organizers[0].progress_pct == 0

    def test_track_rows_carry_their_managers_and_a_no_track_row_reads_as_zero(self):
        service = EventConfirmationsService(
            facilitators=FakeFacilitators([]),
            agenda_items=FakeAgendaItems(
                rows=[
                    _row(
                        key=_RPG_TRACK,
                        name="RPG",
                        facilitators=2,
                        scheduled=4,
                        confirmed=2,
                    ),
                    _row(key=None, name="", facilitators=1, scheduled=1, confirmed=0),
                ],
                without_facilitator=_ORPHANS,
            ),
            tracks=FakeTracks({_RPG_TRACK: ["Ada", "Ben"]}),
            sessions=None,
        )

        dashboard = service.dashboard(_EVENT)

        assert dashboard.tracks[0].manager_names == ["Ada", "Ben"]
        assert dashboard.tracks[0].progress_pct == _HALF
        assert dashboard.tracks[1].track_pk == 0
        assert dashboard.tracks[1].manager_names == []
        assert dashboard.without_facilitator_count == _ORPHANS

    def test_a_no_track_row_borrows_no_managers(self):
        service = EventConfirmationsService(
            facilitators=FakeFacilitators([]),
            agenda_items=FakeAgendaItems(
                rows=[_row(key=None, name="", facilitators=1, scheduled=1, confirmed=0)]
            ),
            tracks=FakeTracks({1: ["Zed"]}),
            sessions=None,
        )

        dashboard = service.dashboard(_EVENT)

        assert dashboard.tracks[0].manager_names == []
