from typing import Protocol

from pydantic import BaseModel

from ludamus.pacts.legacy import CategoryStats, ProposalCategoryDTO


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
