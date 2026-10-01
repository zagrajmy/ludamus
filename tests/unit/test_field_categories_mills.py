from ludamus.mills.submissions.field_categories import CFPFieldCategoryService
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.submissions import RequirementSelectionDTO
from tests.unit.factories import FakeTransaction, category

EVENT_PK = 10


class FakeFields:
    def __init__(self, fields=()):
        self.rows = {(EVENT_PK, field.slug): field for field in fields}
        self.updated = {}

    def create(self, event_id, data):
        field = OrganizerFieldDTO(
            field_type="text",
            name=data["name"],
            order=0,
            pk=len(self.rows) + 1,
            question="?",
            slug=data["name"].lower(),
        )
        self.rows[event_id, field.slug] = field
        return field

    def read_by_slug(self, event_id, slug):
        return self.rows[event_id, slug]

    def update(self, pk, data):
        self.updated[pk] = data


class FakeCategories:
    def __init__(self, categories=()):
        self._categories = {EVENT_PK: list(categories)}
        self.links = {}

    def list_by_event(self, event_id):
        return self._categories.get(event_id, [])

    def set_links(self, field_pk, scoped):
        self.links[field_pk] = scoped


class LinkingService(CFPFieldCategoryService):
    def _set_categories(self, field_pk, scoped):
        self._categories.set_links(field_pk, scoped)


def _category(pk):
    return category(pk=pk, name=f"Cat {pk}", slug=f"cat-{pk}")


def _field(pk=1, slug="vegan"):
    return OrganizerFieldDTO(
        field_type="text", name="Vegan", order=0, pk=pk, question="?", slug=slug
    )


def _service(*, fields=(), categories=()):
    fake_fields = FakeFields(fields)
    fake_categories = FakeCategories(categories)
    service = LinkingService(
        transaction=FakeTransaction(), fields=fake_fields, categories=fake_categories
    )
    return service, fake_fields, fake_categories


def test_create_links_only_the_events_own_categories():
    service, _fields, categories = _service(categories=[_category(1)])

    field = service.create(
        event_pk=EVENT_PK,
        data={"name": "Diet"},
        category_requirements=RequirementSelectionDTO(
            requirements={1: True, 99: False}, order=[]
        ),
    )

    assert field.slug == "diet"
    assert categories.links == {field.pk: {1: True}}


def test_create_without_matching_categories_writes_no_links():
    service, _fields, categories = _service(categories=[_category(1)])

    service.create(
        event_pk=EVENT_PK,
        data={"name": "Diet"},
        category_requirements=RequirementSelectionDTO(
            requirements={99: True}, order=[]
        ),
    )

    assert not categories.links


def test_update_links_only_the_events_own_categories():
    service, fields, categories = _service(fields=[_field()], categories=[_category(1)])

    service.update(
        event_pk=EVENT_PK,
        field_slug="vegan",
        data={"name": "Vegan?"},
        category_requirements=RequirementSelectionDTO(
            requirements={1: True, 99: False}, order=[]
        ),
    )

    assert fields.updated == {1: {"name": "Vegan?"}}
    assert categories.links == {1: {1: True}}


def test_update_rewrites_links_even_to_empty():
    service, fields, categories = _service(fields=[_field()], categories=[_category(1)])
    categories.links[1] = {1: True}

    service.update(
        event_pk=EVENT_PK,
        field_slug="vegan",
        data={"name": "Vegan?"},
        category_requirements=RequirementSelectionDTO(requirements={}, order=[]),
    )

    assert fields.updated == {1: {"name": "Vegan?"}}
    assert categories.links == {1: {}}
