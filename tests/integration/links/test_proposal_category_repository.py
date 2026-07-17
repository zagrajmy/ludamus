from ludamus.links.db.django.models import (
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    ProposalCategory,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
)
from ludamus.links.db.django.repositories import ProposalCategoryRepository
from tests.integration.conftest import EventFactory, ProposalCategoryFactory


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


class TestListPersonalFieldRequirements:
    @staticmethod
    def _create_field_with_options(category, *, name, slug):
        field = PersonalDataField.objects.create(
            event=category.event,
            name=name,
            question=f"{name}?",
            slug=slug,
            field_type="select",
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Zeta", value="z", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Beta", value="b", order=1
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Alpha", value="a", order=1
        )
        PersonalDataFieldRequirement.objects.create(category=category, field=field)

    def test_orders_options_by_order_then_label(self):
        category = ProposalCategoryFactory()
        self._create_field_with_options(category, name="Diet", slug="diet")

        result = ProposalCategoryRepository.list_personal_field_requirements(
            category.pk
        )

        assert [o.label for o in result[0].field.options] == ["Zeta", "Alpha", "Beta"]

    def test_query_count_is_constant_across_fields(self, django_assert_num_queries):
        category = ProposalCategoryFactory()
        self._create_field_with_options(category, name="Diet", slug="diet")
        self._create_field_with_options(category, name="Shirt", slug="shirt")

        with django_assert_num_queries(2):
            ProposalCategoryRepository.list_personal_field_requirements(category.pk)


class TestListSessionFieldRequirements:
    @staticmethod
    def _create_field_with_options(category, *, name, slug):
        field = SessionField.objects.create(
            event=category.event,
            name=name,
            question=f"{name}?",
            slug=slug,
            field_type="select",
        )
        SessionFieldOption.objects.create(field=field, label="Zeta", value="z", order=0)
        SessionFieldOption.objects.create(field=field, label="Beta", value="b", order=1)
        SessionFieldOption.objects.create(
            field=field, label="Alpha", value="a", order=1
        )
        SessionFieldRequirement.objects.create(category=category, field=field)

    def test_orders_options_by_order_then_label(self):
        category = ProposalCategoryFactory()
        self._create_field_with_options(category, name="System", slug="system")

        result = ProposalCategoryRepository.list_session_field_requirements(category.pk)

        assert [o.label for o in result[0].field.options] == ["Zeta", "Alpha", "Beta"]

    def test_query_count_is_constant_across_fields(self, django_assert_num_queries):
        category = ProposalCategoryFactory()
        self._create_field_with_options(category, name="System", slug="system")
        self._create_field_with_options(category, name="Tone", slug="tone")

        with django_assert_num_queries(2):
            ProposalCategoryRepository.list_session_field_requirements(category.pk)
