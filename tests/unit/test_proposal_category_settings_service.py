from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from ludamus.mills.submissions.proposal_category_settings import (
    ProposalCategorySettingsService,
)
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.legacy import PromotionMode, ProposalCategoryDTO, TimeSlotDTO
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


def _personal_field(pk: int) -> OrganizerFieldDTO:
    return OrganizerFieldDTO(
        field_type="text",
        name=f"Personal {pk}",
        order=pk,
        pk=pk,
        question="Question",
        slug=f"personal-{pk}",
    )


def _session_field(pk: int) -> OrganizerFieldDTO:
    return OrganizerFieldDTO(
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


def _mock_repos() -> tuple[ProposalCategorySettingsRepos, MagicMock]:
    categories = MagicMock()
    categories.read_by_slug.return_value = _category()
    personal_fields = MagicMock()
    personal_fields.list_by_event.return_value = [_personal_field(1)]
    session_fields = MagicMock()
    session_fields.list_by_event.return_value = [_session_field(2)]
    time_slots = MagicMock()
    time_slots.list_by_event.return_value = [_time_slot(3)]
    repos = ProposalCategorySettingsRepos(
        categories=categories,
        personal_fields=personal_fields,
        session_fields=session_fields,
        time_slots=time_slots,
        sessions=MagicMock(),
    )
    return repos, categories


def test_update_is_atomic_and_drops_cross_event_requirements() -> None:
    transaction = RecordingTransaction()
    repos, categories = _mock_repos()
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
    categories.update.assert_called_once_with(
        7,
        {
            "name": "RPG",
            "description": "Games",
            "start_time": None,
            "end_time": None,
            "durations": ["PT4H"],
            "min_participants_limit": 2,
            "max_participants_limit": 5,
            "promotion_mode": PromotionMode.OFFER_CLAIM,
            "offer_claim_window": timedelta(minutes=30),
        },
    )
    categories.set_field_requirements.assert_called_once_with(7, {1: True}, [1])
    categories.set_session_field_requirements.assert_called_once_with(
        7, {2: False}, [2]
    )
    categories.set_time_slot_requirements.assert_called_once_with(7, {3: True}, [3])
    assert transaction.active is False


def test_update_leaves_promotion_config_untouched_when_not_submitted() -> None:
    repos, categories = _mock_repos()
    data = _data().model_copy(
        update={"promotion_mode": None, "offer_claim_window": None}
    )

    _service(RecordingTransaction(), repos).update(
        event_id=4, category_slug="rpg", data=data
    )

    payload = categories.update.call_args.args[1]
    assert "promotion_mode" not in payload
    assert "offer_claim_window" not in payload
    assert payload["name"] == "RPG"


def test_read_context_sorts_by_saved_order_and_appends_unordered() -> None:
    repos, categories = _mock_repos()
    repos.personal_fields.list_by_event.return_value = [
        _personal_field(1),
        _personal_field(2),
        _personal_field(3),
    ]
    categories.get_field_order.return_value = [3, 1]
    categories.get_session_field_order.return_value = []
    categories.get_time_slot_order.return_value = []
    categories.get_field_requirements.return_value = {3: True}
    categories.get_session_field_requirements.return_value = {}
    categories.get_time_slot_requirements.return_value = {}
    proposal_count = 5
    repos.sessions.count_by_category.return_value = proposal_count

    page = _service(RecordingTransaction(), repos).read_context(4, "rpg")

    assert [field.pk for field in page.available_fields] == [3, 1, 2]
    assert page.proposal_count == proposal_count


def assert_transaction_active(transaction: RecordingTransaction) -> None:
    assert transaction.active is True
