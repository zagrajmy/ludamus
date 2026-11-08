import pytest

from ludamus.mills.propose.session_fields import CFPSessionFieldService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.propose import RequirementSelectionDTO
from tests.unit.factories import FakeTransaction, category


class FakeFields:
    def __init__(self, field, *, required_by=None, event_id=10):
        self._field = field
        self._event_id = event_id
        self.required_by = required_by or {}
        self.created = {}
        self.updated = {}
        self.deleted = []

    def list_by_event(self, event_id):
        return [self._field] if event_id == self._event_id else []

    def get_usage_counts(self, event_id):
        return self.required_by if event_id == self._event_id else {}

    def has_requirements(self, pk):
        return bool(self.required_by.get(pk))

    def delete(self, pk):
        self.deleted.append(pk)

    def create(self, event_id, data):
        self.created[event_id] = data
        return self._field

    def read_by_slug(self, event_id, slug):
        if event_id != self._event_id or slug != self._field.slug:
            raise NotFoundError
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

    def get_session_field_categories(self, field_pk):
        return self.session_links.get(field_pk, {})


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


def _service(fields, categories=None):
    return CFPSessionFieldService(
        transaction=FakeTransaction(),
        fields=fields,
        categories=categories or FakeCategories([]),
    )


def test_summaries_count_required_and_optional_uses_per_field():
    field = _field()
    service = _service(FakeFields(field, required_by={3: {"required": 2}}))

    (summary,) = service.list_summaries(10)

    assert (summary.field, summary.required_count, summary.optional_count) == (
        field,
        2,
        0,
    )
    assert summary.is_used


def test_read_returns_the_field_with_its_category_links():
    categories = FakeCategories([_category(1)])
    categories.session_links[3] = {1: True}
    service = _service(FakeFields(_field()), categories)

    assert service.read(10, "triggers") == (_field(), {1: True})
    assert service.list_categories(10) == [_category(1)]


def test_delete_removes_a_field_no_category_asks_for():
    fields = FakeFields(_field())

    assert _service(fields).delete(10, "triggers")
    assert fields.deleted == [3]


def test_delete_keeps_a_field_a_category_asks_for():
    fields = FakeFields(_field(), required_by={3: {"optional": 1}})

    assert not _service(fields).delete(10, "triggers")
    assert not fields.deleted


def test_delete_of_another_events_field_is_not_found_and_deletes_nothing():
    fields = FakeFields(_field())

    with pytest.raises(NotFoundError):
        _service(fields).delete(11, "triggers")
    assert not fields.deleted
