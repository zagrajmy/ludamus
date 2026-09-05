"""The spot picker's pure helpers: no DB, no request, no template."""

from datetime import UTC, datetime

import pytest

from ludamus.gates.web.django.event.propose_spot import describe_spot, pick_spot
from ludamus.pacts.legacy import TimeSlotDTO
from ludamus.pacts.propose import SpotClaim
from ludamus.pacts.timetable import FreeSpotSpaceDTO

_START = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)
_END = datetime(2026, 7, 1, 20, 0, tzinfo=UTC)


def _free_space(pk, *, slot_pk, group=""):
    return FreeSpotSpaceDTO(
        pk=pk,
        name=f"Room {pk}",
        group=group,
        slots=[TimeSlotDTO(pk=slot_pk, start_time=_START, end_time=_END)],
    )


class TestPickSpot:
    @pytest.mark.parametrize("raw", (None, ""))
    def test_an_unanswered_picker_names_no_spot(self, raw):
        assert pick_spot([_free_space(1, slot_pk=10)], raw) is None

    @pytest.mark.parametrize("raw", ("1", "1:", "room:10", "1:slot"))
    def test_a_malformed_pair_names_no_spot(self, raw):
        assert pick_spot([_free_space(1, slot_pk=10)], raw) is None

    def test_a_free_cell_is_resolved(self):
        assert pick_spot([_free_space(1, slot_pk=10)], "1:10") == SpotClaim(1, 10)


class TestDescribeSpot:
    def test_it_walks_past_the_rooms_the_claim_does_not_name(self):
        spaces = [_free_space(1, slot_pk=10), _free_space(2, slot_pk=20, group="Wing")]

        described = describe_spot(spaces, SpotClaim(2, 20))

        assert described == {
            "space_name": "Room 2",
            "group": "Wing",
            "start_time": _START,
            "end_time": _END,
        }

    def test_a_claim_on_a_slot_the_room_lost_describes_nothing(self):
        assert describe_spot([_free_space(1, slot_pk=10)], SpotClaim(1, 99)) is None
