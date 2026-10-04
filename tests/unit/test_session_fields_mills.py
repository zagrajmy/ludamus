from ludamus.mills.submissions.session_fields import CFPSessionFieldService
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.submissions import RequirementSelectionDTO
from tests.unit.factories import FakeTransaction, category


class FakeFields:
    def __init__(self, field):
        self._field = field
        self.created = {}
        self.updated = {}

    def create(self, event_id, data):
        self.created[event_id] = data
        return self._field

    def read_by_slug(self, _event_id, _slug):
        return self._field

    def update(self, pk, data):
        self.updated[pk] = data


class FakeCategories:
    def __init__(self, categories):
        self._categories = categories
        self.session_links = {}

    def list_by_event(self, _event_id):
        return self._categories

    def set_session_field_categories(self, field_pk, scoped):
        self.session_links[field_pk] = scoped


def _category(pk):
    return category(pk=pk, name=f"Cat {pk}", slug=f"cat-{pk}")


def _field():
    return OrganizerFieldDTO(
        field_type="text", name="Triggers", order=0, pk=3, question="?", slug="triggers"
    )


def test_create_writes_session_field_links_scoped_to_the_event():
    categories = FakeCategories([_category(1)])
    fields = FakeFields(_field())
    service = CFPSessionFieldService(
        transaction=FakeTransaction(), fields=fields, categories=categories
    )

    service.create(
        event_pk=10,
        data={"name": "Triggers"},
        category_requirements=RequirementSelectionDTO(
            requirements={1: False, 42: True}, order=[]
        ),
    )

    assert fields.created == {10: {"name": "Triggers"}}
    assert categories.session_links == {3: {1: False}}


def test_update_replaces_session_field_links():
    categories = FakeCategories([_category(1), _category(2)])
    fields = FakeFields(_field())
    service = CFPSessionFieldService(
        transaction=FakeTransaction(), fields=fields, categories=categories
    )

    service.update(
        event_pk=10,
        field_slug="triggers",
        data={"name": "Content warnings"},
        category_requirements=RequirementSelectionDTO(
            requirements={2: True}, order=[2]
        ),
    )

    assert fields.updated == {3: {"name": "Content warnings"}}
    assert categories.session_links == {3: {2: True}}
