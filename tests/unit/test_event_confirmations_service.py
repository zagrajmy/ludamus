from ludamus.mills.event import EventConfirmationsService
from ludamus.pacts.legacy import ConfirmationCountsRow, ConfirmationTotalsRow

_ADA = 11
_BEN = 12
_RPG_TRACK = 21
_TALKS_TRACK = 22

_EVENT_SCHEDULED = 11
_EVENT_CONFIRMED = 7
_EVENT_PCT = 64
_UNCLAIMED_FACILITATORS = 5
_CLAIMED_FACILITATORS = 3
_FULLY_CONFIRMED_PCT = 100
_ITEMS_WITHOUT_FACILITATOR = 3


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
        self._rows = rows
        self.calls: list[int] = []

    def count_confirmations_by_organizer(
        self, event_pk: int
    ) -> list[ConfirmationCountsRow]:
        self.calls.append(event_pk)
        return self._rows


class FakeAgendaItems:
    def __init__(
        self,
        *,
        rows: list[ConfirmationCountsRow],
        without_facilitator: int = 0,
        totals: ConfirmationTotalsRow | None = None,
    ) -> None:
        self._rows = rows
        self._without_facilitator = without_facilitator
        self._totals = totals or ConfirmationTotalsRow(
            scheduled_count=0, confirmed_count=0
        )
        self.calls: list[int] = []

    def count_confirmations_by_track(
        self, event_pk: int
    ) -> list[ConfirmationCountsRow]:
        self.calls.append(event_pk)
        return self._rows

    def count_without_facilitator(self, event_pk: int) -> int:
        self.calls.append(event_pk)
        return self._without_facilitator

    def count_event_totals(self, event_pk: int) -> ConfirmationTotalsRow:
        self.calls.append(event_pk)
        return self._totals


class FakeTracks:
    def __init__(self, names: dict[int, list[str]]) -> None:
        self._names = names
        self.calls: list[int] = []

    def list_manager_names_by_event(self, event_pk: int) -> dict[int, list[str]]:
        self.calls.append(event_pk)
        return self._names


def _service(
    *,
    organizer_rows: list[ConfirmationCountsRow] | None = None,
    track_rows: list[ConfirmationCountsRow] | None = None,
    manager_names: dict[int, list[str]] | None = None,
    without_facilitator: int = 0,
    totals: ConfirmationTotalsRow | None = None,
) -> tuple[EventConfirmationsService, FakeFacilitators, FakeAgendaItems, FakeTracks]:
    facilitators = FakeFacilitators(organizer_rows or [])
    agenda_items = FakeAgendaItems(
        rows=track_rows or [], without_facilitator=without_facilitator, totals=totals
    )
    tracks = FakeTracks(manager_names or {})
    service = EventConfirmationsService(
        facilitators=facilitators,
        agenda_items=agenda_items,
        tracks=tracks,
        sessions=None,
    )
    return service, facilitators, agenda_items, tracks


class TestDashboard:
    def test_totals_come_from_the_items_not_from_the_organizer_rows(self):
        # The rows add up to 12 because one item is run by two facilitators
        # claimed by different organizers. The event has 11.
        service, _, _, _ = _service(
            organizer_rows=[
                _row(key=_ADA, name="Ada", facilitators=3, scheduled=8, confirmed=6),
                _row(key=_BEN, name="Ben", facilitators=2, scheduled=4, confirmed=1),
            ],
            totals=ConfirmationTotalsRow(
                scheduled_count=_EVENT_SCHEDULED, confirmed_count=_EVENT_CONFIRMED
            ),
        )

        dashboard = service.dashboard(1)

        assert dashboard.scheduled_count == _EVENT_SCHEDULED
        assert dashboard.confirmed_count == _EVENT_CONFIRMED
        assert dashboard.progress_pct == _EVENT_PCT

    def test_unclaimed_row_counts_apart_from_claimed(self):
        service, _, _, _ = _service(
            organizer_rows=[
                _row(key=None, name="", facilitators=5, scheduled=9, confirmed=0),
                _row(key=_ADA, name="Ada", facilitators=3, scheduled=8, confirmed=6),
            ]
        )

        dashboard = service.dashboard(1)

        assert dashboard.unclaimed_facilitator_count == _UNCLAIMED_FACILITATORS
        assert dashboard.claimed_facilitator_count == _CLAIMED_FACILITATORS
        assert dashboard.organizers[0].organizer_id is None
        assert not dashboard.organizers[0].organizer_name

    def test_progress_is_zero_when_nothing_is_scheduled(self):
        service, _, _, _ = _service(
            organizer_rows=[
                _row(key=_ADA, name="Ada", facilitators=2, scheduled=0, confirmed=0)
            ],
            totals=ConfirmationTotalsRow(scheduled_count=0, confirmed_count=0),
        )

        dashboard = service.dashboard(1)

        assert dashboard.progress_pct == 0
        assert dashboard.organizers[0].progress_pct == 0

    def test_track_rows_carry_their_managers(self):
        service, _, _, _ = _service(
            track_rows=[
                _row(
                    key=_RPG_TRACK,
                    name="RPG",
                    facilitators=4,
                    scheduled=10,
                    confirmed=10,
                ),
                _row(
                    key=_TALKS_TRACK,
                    name="Talks",
                    facilitators=2,
                    scheduled=3,
                    confirmed=0,
                ),
            ],
            manager_names={_RPG_TRACK: ["Ada", "Ben"]},
        )

        dashboard = service.dashboard(1)

        assert dashboard.tracks[0].manager_names == ["Ada", "Ben"]
        assert dashboard.tracks[0].progress_pct == _FULLY_CONFIRMED_PCT
        assert dashboard.tracks[1].manager_names == []
        assert dashboard.tracks[1].progress_pct == 0

    def test_sessions_without_a_facilitator_are_reported(self):
        service, _, _, _ = _service(without_facilitator=_ITEMS_WITHOUT_FACILITATOR)

        dashboard = service.dashboard(1)

        assert dashboard.without_facilitator_count == _ITEMS_WITHOUT_FACILITATOR

    def test_every_repository_is_asked_about_the_same_event(self):
        service, facilitators, agenda_items, tracks = _service()

        service.dashboard(42)

        assert facilitators.calls == [42]
        assert agenda_items.calls == [42, 42, 42]
        assert tracks.calls == [42]
