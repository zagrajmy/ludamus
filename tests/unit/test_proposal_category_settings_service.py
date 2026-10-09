from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from ludamus.mills.submissions.proposal_category_settings import (
    ProposalCategorySettingsService,
)
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.legacy import PromotionMode, ProposalCategoryDTO
from ludamus.pacts.submissions import (
    ProposalCategoryEditContextDTO,
    ProposalCategorySettingsData,
    ProposalCategorySettingsRepos,
    RequirementSelectionDTO,
)

EVENT_ID = 4
CATEGORY_PK = 7
_START = datetime(2026, 8, 1, 10, tzinfo=UTC)
_END = datetime(2026, 8, 1, 18, tzinfo=UTC)


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
        pk=CATEGORY_PK,
        slug="rpg",
        start_time=None,
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


def _data() -> ProposalCategorySettingsData:
    return ProposalCategorySettingsData(
        name="RPG",
        description="Games",
        start_time=_START,
        end_time=_END,
        durations=["PT4H"],
        min_participants_limit=2,
        max_participants_limit=5,
        promotion_mode=PromotionMode.OFFER_CLAIM,
        offer_claim_window=timedelta(minutes=30),
        session_fields=RequirementSelectionDTO(
            requirements={2: False, 999: False}, order=[2, 999]
        ),
        asks_availability=True,
    )


class FakeCategories:
    def __init__(
        self,
        *,
        session_field_order=(),
        session_field_requirements=None,
        transaction=None,
    ):
        self._by_slug = {(EVENT_ID, "rpg"): _category()}
        self._orders = {CATEGORY_PK: list(session_field_order)}
        self._requirements = {CATEGORY_PK: session_field_requirements or {}}
        self._transaction = transaction
        self.active_during_writes: list[bool] = []
        self.updated = []
        self.requirements_set = []

    def read_by_slug(self, event_id, slug):
        return self._by_slug[event_id, slug]

    def get_session_field_order(self, category_id):
        return self._orders[category_id]

    def get_session_field_requirements(self, category_id):
        return self._requirements[category_id]

    def update(self, pk, data):
        self._note_write()
        self.updated.append((pk, data))

    def set_session_field_requirements(self, category_id, requirements, order):
        self._note_write()
        self.requirements_set.append((category_id, requirements, order))

    def _note_write(self):
        if self._transaction is not None:
            self.active_during_writes.append(self._transaction.active)


class FakeListByEvent:
    def __init__(self, items):
        self._items = {EVENT_ID: list(items)}

    def list_by_event(self, event_id):
        return self._items.get(event_id, [])


class FakeSessions:
    def __init__(self, proposal_count):
        self._counts = {CATEGORY_PK: proposal_count}

    def count_by_category(self, category_id):
        return self._counts[category_id]


def _repos(
    *, categories=None, session_fields=None, proposal_count=0
) -> ProposalCategorySettingsRepos:
    return ProposalCategorySettingsRepos(
        categories=categories or FakeCategories(),
        session_fields=FakeListByEvent(session_fields or [_session_field(2)]),
        sessions=FakeSessions(proposal_count),
    )


def _service(repos: ProposalCategorySettingsRepos, transaction=None):
    return ProposalCategorySettingsService(transaction or RecordingTransaction(), repos)


def test_update_writes_everything_inside_one_transaction() -> None:
    transaction = RecordingTransaction()
    categories = FakeCategories(transaction=transaction)

    _service(_repos(categories=categories), transaction).update(
        event_id=EVENT_ID, category_slug="rpg", data=_data()
    )

    assert categories.active_during_writes == [True, True]
    assert transaction.active is False


def test_update_leaves_promotion_config_untouched_when_not_submitted() -> None:
    categories = FakeCategories()
    data = _data().model_copy(
        update={"promotion_mode": None, "offer_claim_window": None}
    )

    _service(_repos(categories=categories)).update(
        event_id=EVENT_ID, category_slug="rpg", data=data
    )

    assert categories.updated == [
        (
            CATEGORY_PK,
            {
                "name": "RPG",
                "description": "Games",
                "start_time": _START,
                "end_time": _END,
                "durations": ["PT4H"],
                "min_participants_limit": 2,
                "max_participants_limit": 5,
                "asks_availability": True,
            },
        )
    ]


def test_read_context_sorts_by_saved_order_and_appends_unordered() -> None:
    categories = FakeCategories(
        session_field_order=[3, 1], session_field_requirements={3: True}
    )
    repos = _repos(
        categories=categories,
        session_fields=[_session_field(1), _session_field(2), _session_field(3)],
        proposal_count=5,
    )

    page = _service(repos).read_context(EVENT_ID, "rpg")

    assert page == ProposalCategoryEditContextDTO(
        category=_category(),
        available_session_fields=[
            _session_field(3),
            _session_field(1),
            _session_field(2),
        ],
        session_field_requirements={3: True},
        session_field_order=[3, 1],
        asks_availability=False,
        proposal_count=5,
    )


def test_update_writes_submitted_promotion_config() -> None:
    categories = FakeCategories()

    _service(_repos(categories=categories)).update(
        event_id=EVENT_ID, category_slug="rpg", data=_data()
    )

    assert categories.updated == [
        (
            CATEGORY_PK,
            {
                "name": "RPG",
                "description": "Games",
                "start_time": _START,
                "end_time": _END,
                "durations": ["PT4H"],
                "min_participants_limit": 2,
                "max_participants_limit": 5,
                "promotion_mode": PromotionMode.OFFER_CLAIM,
                "offer_claim_window": timedelta(minutes=30),
                "asks_availability": True,
            },
        )
    ]
    assert categories.requirements_set == [(CATEGORY_PK, {2: False}, [2])]
