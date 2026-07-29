from unittest.mock import MagicMock

import pytest

from ludamus.mills.facilitator_roster import FacilitatorRosterService
from ludamus.pacts import FacilitatorDTO, NotFoundError
from ludamus.pacts.legacy import FacilitatorListItemDTO


def _facilitator(pk=1, event_id=7):
    return FacilitatorDTO(
        accreditation_type="standard",
        display_name="Ada",
        event_id=event_id,
        pk=pk,
        slug="ada",
        user_id=None,
    )


def _list_item(pk=1):
    return FacilitatorListItemDTO(
        accreditation_type="standard",
        display_name="Ada",
        pk=pk,
        session_count=0,
        slug="ada",
        user_id=None,
    )


class TestFacilitatorRosterService:
    @pytest.fixture
    def facilitators(self):
        return MagicMock()

    @pytest.fixture
    def service(self, facilitators):
        return FacilitatorRosterService(facilitators)

    def test_list_by_event_delegates(self, service, facilitators):
        items = [_list_item(pk=1), _list_item(pk=2)]
        facilitators.list_by_event.return_value = items

        result = service.list_by_event(7)

        assert result == items
        facilitators.list_by_event.assert_called_once_with(7)

    def test_read_scoped_returns_facilitator_from_current_event(
        self, service, facilitators
    ):
        facilitator = _facilitator(pk=3, event_id=7)
        facilitators.read.return_value = facilitator

        result = service.read_scoped(event_pk=7, facilitator_id=3)

        assert result == facilitator
        facilitators.read.assert_called_once_with(3)

    def test_read_scoped_rejects_foreign_event_facilitator(self, service, facilitators):
        facilitators.read.return_value = _facilitator(pk=3, event_id=8)

        with pytest.raises(NotFoundError):
            service.read_scoped(event_pk=7, facilitator_id=3)

    def test_read_scoped_propagates_not_found(self, service, facilitators):
        facilitators.read.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.read_scoped(event_pk=7, facilitator_id=999)
