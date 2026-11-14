from datetime import datetime, timedelta
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.enrollment import PromotionMode
from ludamus.pacts.fields import OrganizerFieldDTO


class ProposalCategoriesPageDTO(BaseModel):
    categories: list[ProposalCategoryDTO]
    stats: dict[int, CategoryStats]
    # Categories `delete_by_slug` would refuse, so the list can say so where the
    # Delete button would be instead of taking the click.
    undeletable_pks: frozenset[int]


class ProposalCategoriesRepositoryProtocol(Protocol):
    def create(self, event_id: int, name: str) -> ProposalCategoryDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def get_category_stats(event_id: int) -> dict[int, CategoryStats]: ...
    @staticmethod
    def has_proposals(pk: int) -> bool: ...
    @staticmethod
    def pks_with_proposals(event_id: int) -> frozenset[int]: ...
    @staticmethod
    def list_by_event(event_id: int) -> list[ProposalCategoryDTO]: ...
    @staticmethod
    def read_by_slug(event_id: int, slug: str) -> ProposalCategoryDTO: ...


class ProposalCategoriesServiceProtocol(Protocol):
    def get_page_context(self, event_pk: int) -> ProposalCategoriesPageDTO: ...
    def create(self, event_pk: int, name: str) -> ProposalCategoryDTO: ...
    def delete_by_slug(self, event_pk: int, category_slug: str) -> bool: ...


class ProposalCategoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asks_availability: bool = False
    description: str
    durations: list[str]
    end_time: datetime | None
    max_participants_limit: int
    min_participants_limit: int
    name: str
    offer_claim_window: timedelta = timedelta(hours=24)
    pk: int
    promotion_mode: PromotionMode = PromotionMode.AUTO
    slug: str
    start_time: datetime | None


class ProposalCategoryData(TypedDict, total=False):
    asks_availability: bool
    description: str
    durations: list[str]
    end_time: datetime | None
    max_participants_limit: int
    min_participants_limit: int
    name: str
    offer_claim_window: timedelta
    promotion_mode: PromotionMode
    start_time: datetime | None


class CategoryStats(TypedDict):
    """Statistics for a proposal category."""

    proposals_count: int
    accepted_count: int


class SessionFieldRequirementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field: OrganizerFieldDTO
    is_required: bool


class ProposalCategoryRepositoryProtocol(Protocol):
    def create(self, event_id: int, name: str) -> ProposalCategoryDTO: ...
    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def get_category_stats(event_id: int) -> dict[int, CategoryStats]: ...
    @staticmethod
    def asks_availability(category_id: int) -> bool: ...
    @staticmethod
    def get_session_field_order(category_id: int) -> list[int]: ...
    @staticmethod
    def get_session_field_requirements(category_id: int) -> dict[int, bool]: ...
    @staticmethod
    def has_proposals(pk: int) -> bool: ...
    @staticmethod
    def list_by_event(event_id: int) -> list[ProposalCategoryDTO]: ...
    @staticmethod
    def read(pk: int, event_id: int) -> ProposalCategoryDTO: ...
    @staticmethod
    def read_by_slug(event_id: int, slug: str) -> ProposalCategoryDTO: ...
    @staticmethod
    def list_session_field_requirements(
        category_id: int,
    ) -> list[SessionFieldRequirementDTO]: ...
    @staticmethod
    def set_session_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None: ...
    @staticmethod
    def get_session_field_categories(field_id: int) -> dict[int, bool]: ...
    @staticmethod
    def set_session_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None: ...
    def update(self, pk: int, data: ProposalCategoryData) -> ProposalCategoryDTO: ...
