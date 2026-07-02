from ludamus.adapters.db.django.models import ProposalCategory
from ludamus.links.db.django.repositories import ProposalCategoryRepository
from tests.integration.conftest import EventFactory


class TestProposalCategoryRepositoryGetOrCreateBySlug:
    def test_creates_a_category_with_the_given_name_and_slug(self):
        event = EventFactory.create()

        pk = ProposalCategoryRepository.get_or_create_by_slug(event.pk, "RPG", "rpg")

        category = ProposalCategory.objects.get(pk=pk)
        assert category.name == "RPG"
        assert category.slug == "rpg"
        assert category.event_id == event.pk

    def test_reuses_an_existing_category_by_slug(self):
        event = EventFactory.create()
        first = ProposalCategoryRepository.get_or_create_by_slug(event.pk, "RPG", "rpg")

        second = ProposalCategoryRepository.get_or_create_by_slug(
            event.pk, "RPG sessions", "rpg"
        )

        assert second == first
        assert ProposalCategory.objects.filter(event=event).count() == 1
