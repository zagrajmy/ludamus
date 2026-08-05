from unittest.mock import MagicMock

import pytest

from ludamus.mills.proposal_categories import ProposalCategoriesService
from ludamus.pacts import NotFoundError, ProposalCategoryDTO
from ludamus.pacts.proposal_categories import ProposalCategoriesPageDTO


def _category(*, pk=1, name="Talk", slug="talk"):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=0,
        min_participants_limit=0,
        name=name,
        pk=pk,
        slug=slug,
        start_time=None,
    )


class TestProposalCategoriesService:
    @pytest.fixture
    def categories(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def service(self, transaction, categories):
        return ProposalCategoriesService(transaction, categories)

    def test_get_page_context_bundles_categories_with_stats(self, service, categories):
        cats = [_category(pk=1), _category(pk=2, name="RPG", slug="rpg")]
        stats = {1: {"proposals_count": 3, "accepted_count": 1}}
        categories.list_by_event.return_value = cats
        categories.get_category_stats.return_value = stats

        page = service.get_page_context(7)

        assert isinstance(page, ProposalCategoriesPageDTO)
        assert page.categories == cats
        assert page.stats == stats
        categories.list_by_event.assert_called_once_with(7)
        categories.get_category_stats.assert_called_once_with(7)

    def test_create_persists_in_transaction(self, service, transaction, categories):
        created = _category(pk=9, name="Workshop", slug="workshop")
        categories.create.return_value = created

        result = service.create(7, "Workshop")

        assert result == created
        categories.create.assert_called_once_with(7, "Workshop")
        transaction.atomic.assert_called_once_with()

    def test_delete_by_slug_deletes_category_without_proposals(
        self, service, transaction, categories
    ):
        categories.read_by_slug.return_value = _category(pk=5)
        categories.has_proposals.return_value = False

        deleted = service.delete_by_slug(7, "talk")

        assert deleted is True
        categories.read_by_slug.assert_called_once_with(7, "talk")
        categories.has_proposals.assert_called_once_with(5)
        categories.delete.assert_called_once_with(5)
        transaction.atomic.assert_called_once_with()

    def test_delete_by_slug_refuses_category_with_proposals(self, service, categories):
        categories.read_by_slug.return_value = _category(pk=5)
        categories.has_proposals.return_value = True

        deleted = service.delete_by_slug(7, "talk")

        assert deleted is False
        categories.delete.assert_not_called()

    def test_delete_by_slug_propagates_not_found_without_side_effects(
        self, service, categories
    ):
        categories.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.delete_by_slug(7, "foreign-slug")

        categories.has_proposals.assert_not_called()
        categories.delete.assert_not_called()
