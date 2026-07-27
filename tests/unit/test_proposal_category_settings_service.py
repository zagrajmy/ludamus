from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from ludamus.mills.submissions.proposal_category_settings import (
    ProposalCategorySettingsService,
)
from ludamus.pacts.legacy import (
    PersonalDataFieldDTO,
    PromotionMode,
    ProposalCategoryDTO,
    SessionFieldDTO,
    TimeSlotDTO,
)
from ludamus.pacts.submissions import (
    ProposalCategorySettingsData,
    ProposalCategorySettingsRepos,
    RequirementSelectionDTO,
)


class RecordingTransaction:
    def __init__(self) -> None:
        self.active = False

    @contextmanager
    def atomic(self):
        self.active = True
        try:
            yield
        finally:
            self.active = False


def _category() -> ProposalCategoryDTO:
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=0,
        min_participants_limit=0,
        name="RPG",
        pk=7,
        slug="rpg",
        start_time=None,
    )


def _personal_field(pk: int) -> PersonalDataFieldDTO:
    return PersonalDataFieldDTO(
        field_type="text",
        name=f"Personal {pk}",
        order=pk,
        pk=pk,
        question="Question",
        slug=f"personal-{pk}",
    )


def _session_field(pk: int) -> SessionFieldDTO:
    return SessionFieldDTO(
        field_type="text",
        name=f"Session {pk}",
        order=pk,
        pk=pk,
        question="Question",
        slug=f"session-{pk}",
    )


def _time_slot(pk: int) -> TimeSlotDTO:
    start = datetime(2026, 8, 28, 10, tzinfo=UTC)
    return TimeSlotDTO(pk=pk, start_time=start, end_time=start + timedelta(hours=1))


def _data() -> ProposalCategorySettingsData:
    return ProposalCategorySettingsData(
        name="RPG",
        description="Games",
        start_time=None,
        end_time=None,
        durations=["PT4H"],
        min_participants_limit=2,
        max_participants_limit=5,
        promotion_mode=PromotionMode.OFFER_CLAIM,
        offer_claim_window=timedelta(minutes=30),
        personal_fields=RequirementSelectionDTO(
            requirements={1: True, 999: True}, order=[999, 1]
        ),
        session_fields=RequirementSelectionDTO(
            requirements={2: False, 999: False}, order=[2, 999]
        ),
        time_slots=RequirementSelectionDTO(
            requirements={3: True, 999: True}, order=[999, 3]
        ),
    )


def _service(transaction: RecordingTransaction, repos: ProposalCategorySettingsRepos):
    return ProposalCategorySettingsService(transaction, repos)


def test_update_is_atomic_and_drops_cross_event_requirements() -> None:
    transaction = RecordingTransaction()
    categories = MagicMock()
    categories.read_by_slug.return_value = _category()
    personal_fields = MagicMock()
    personal_fields.list_by_event.return_value = [_personal_field(1)]
    session_fields = MagicMock()
    session_fields.list_by_event.return_value = [_session_field(2)]
    time_slots = MagicMock()
    time_slots.list_by_event.return_value = [_time_slot(3)]
    sessions = MagicMock()
    repos = ProposalCategorySettingsRepos(
        categories=categories,
        personal_fields=personal_fields,
        session_fields=session_fields,
        time_slots=time_slots,
        sessions=sessions,
    )
    mutations = (
        categories.update,
        categories.set_field_requirements,
        categories.set_session_field_requirements,
        categories.set_time_slot_requirements,
    )
    for mutation in mutations:
        mutation.side_effect = lambda *_args: assert_transaction_active(transaction)

    _service(transaction, repos).update(event_id=4, category_slug="rpg", data=_data())

    categories.read_by_slug.assert_called_once_with(4, "rpg")
    categories.set_field_requirements.assert_called_once_with(7, {1: True}, [1])
    categories.set_session_field_requirements.assert_called_once_with(
        7, {2: False}, [2]
    )
    categories.set_time_slot_requirements.assert_called_once_with(7, {3: True}, [3])
    assert transaction.active is False


def assert_transaction_active(transaction: RecordingTransaction) -> None:
    assert transaction.active is True
