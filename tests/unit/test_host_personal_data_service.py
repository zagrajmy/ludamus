from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ludamus.mills.submissions.personal_data_fields import (
    CFPPersonalDataFieldService,
    PersonalDataFieldValueService,
    log_facilitator_deletion,
)
from ludamus.pacts import (
    FacilitatorDTO,
    NotFoundError,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
)
from ludamus.pacts.legacy import FacilitatorChangeLogDTO, ProposalCategoryDTO
from ludamus.pacts.submissions import RequirementSelectionDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def atomic(self):
        return _atomic()


class FakeFacilitators:
    def __init__(self, facilitator):
        self._facilitator = facilitator
        self.updated = []

    def read(self, pk):
        assert pk == self._facilitator.pk
        return self._facilitator

    def update(self, pk, data):
        self.updated.append((pk, data))


class FakePersonalDataFieldValue:
    def __init__(self, existing=None, existing_field_ids=()):
        self.saved = []
        self._existing = existing or {}
        self._existing_field_ids = list(existing_field_ids)

    def save(self, entries):
        self.saved.append(entries)

    def read_for_facilitator_event(self, _facilitator_id, _event_id):
        return dict(self._existing)

    def list_field_ids_for_facilitator_event(self, _facilitator_id, _event_id):
        return list(self._existing_field_ids)


class FakePersonalDataFields:
    def __init__(self, fields=()):
        self._fields = list(fields)

    def list_by_event(self, _event_id):
        return self._fields


class FakeChangeLogs:
    def __init__(self):
        self.created = []

    def create(self, data):
        self.created.append(data)


def _facilitator(event_id=10):
    return FacilitatorDTO(
        accreditation_type="none",
        display_name="Alice",
        event_id=event_id,
        pk=1,
        slug="alice",
        user_id=None,
    )


def _field():
    return OrganizerFieldDTO(
        field_type="checkbox", name="Vegan", order=0, pk=5, question="?", slug="vegan"
    )


def _entry(*, value=True):
    return PersonalDataFieldValueData(
        facilitator_id=1, event_id=10, field_id=5, value=value
    )


def _service(*, facilitators, personal_data_field_values, fields=(), change_logs=None):
    return PersonalDataFieldValueService(
        transaction=FakeTransaction(),
        facilitators=facilitators,
        personal_data_field_values=personal_data_field_values,
        personal_data_fields=FakePersonalDataFields(fields),
        facilitator_change_logs=change_logs or FakeChangeLogs(),
    )


def test_rejects_facilitator_from_other_event():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator(event_id=99)),
        personal_data_field_values=repo,
    )

    with pytest.raises(NotFoundError):
        service.update_personal_data(event_id=10, facilitator_id=1, entries=[_entry()])

    assert not repo.saved


def test_blank_old_and_blank_new_logs_nothing():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={}),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value=False)]
    )

    assert not logs.created


def test_whitespace_only_new_answer_over_an_unset_field_logs_nothing():
    # A whitespace-only value is discarded by storage, so the change log must
    # treat it as unset too — otherwise it records a ghost edit for a row that
    # was never written.
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={}),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value="  ")]
    )

    assert not logs.created


def test_blank_answer_for_an_unanswered_field_stores_nothing():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value="   ")]
    )

    assert not repo.saved


def test_blank_answer_clears_a_field_that_has_one():
    repo = FakePersonalDataFieldValue(existing={"vegan": "yes"}, existing_field_ids=[5])
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value="")]
    )

    assert repo.saved == [[_entry(value="")]]


def test_unchecked_checkbox_is_stored_as_an_answer():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value=False)]
    )

    assert repo.saved == [[_entry(value=False)]]


def test_update_facilitator_rejects_facilitator_from_other_event():
    facilitators = FakeFacilitators(_facilitator(event_id=99))
    service = _service(
        facilitators=facilitators,
        personal_data_field_values=FakePersonalDataFieldValue(),
    )

    with pytest.raises(NotFoundError):
        service.update_facilitator(
            event_id=10,
            facilitator_id=1,
            data={"accreditation_type": "honorary", "internal_comment": ""},
            entries=[],
        )

    assert not facilitators.updated


def test_update_facilitator_logs_personal_data_and_core_changes_in_one_entry():
    logs = FakeChangeLogs()
    facilitators = FakeFacilitators(_facilitator())
    repo = FakePersonalDataFieldValue(existing={"vegan": False})
    service = _service(
        facilitators=facilitators,
        personal_data_field_values=repo,
        fields=[_field()],
        change_logs=logs,
    )

    service.update_facilitator(
        event_id=10,
        facilitator_id=1,
        data={"accreditation_type": "honorary", "internal_comment": ""},
        entries=[_entry(value=True)],
        user_id=7,
    )

    assert facilitators.updated == [
        (1, {"accreditation_type": "honorary", "internal_comment": ""})
    ]
    assert repo.saved == [[_entry(value=True)]]
    assert logs.created == [
        {
            "event_id": 10,
            "facilitator_id": 1,
            "user_id": 7,
            "changes": [
                {"field": "", "field_id": 5, "old": False, "new": True},
                {
                    "field": "accreditation_type",
                    "field_id": None,
                    "old": "none",
                    "new": "honorary",
                },
            ],
        }
    ]


def test_update_facilitator_with_nothing_changed_logs_nothing():
    logs = FakeChangeLogs()
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        change_logs=logs,
    )

    service.update_facilitator(
        event_id=10, facilitator_id=1, data={"accreditation_type": "none"}, entries=[]
    )

    assert not repo.saved
    assert not logs.created


def test_unchanged_answer_and_unknown_field_are_not_logged():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(
            existing={"vegan": "yes"}, existing_field_ids=[5]
        ),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10,
        facilitator_id=1,
        entries=[
            _entry(value="yes"),
            PersonalDataFieldValueData(
                facilitator_id=1, event_id=10, field_id=404, value="stray"
            ),
        ],
    )

    assert not logs.created


def test_emptying_a_multi_select_answer_is_not_an_edit():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={}),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value=[])]
    )

    assert not logs.created


class FakeLogReader(FakeChangeLogs):
    def __init__(self, entries):
        super().__init__()
        self._entries = entries

    def list_by_event(self, _event_id):
        return self._entries


def test_list_log_and_field_names_read_through():
    log_entry = FacilitatorChangeLogDTO(
        pk=1,
        event_id=10,
        facilitator_id=1,
        facilitator_name="Alice",
        user_id=None,
        user_name="",
        changes=[],
        creation_time=datetime(2026, 1, 1, tzinfo=UTC),
    )
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(),
        fields=[_field()],
        change_logs=FakeLogReader([log_entry]),
    )

    assert service.list_log(10) == [log_entry]
    assert service.list_field_names(10) == {5: "Vegan"}


class FakeCFPFields:
    def __init__(self, *, fields=(), usage=None, required_by=()):
        self._fields = list(fields)
        self._usage = usage or {}
        self._required_by = set(required_by)
        self.deleted = []

    def list_by_event(self, _event_id):
        return self._fields

    def get_usage_counts(self, _event_id):
        return self._usage

    def read_by_slug(self, _event_id, slug):
        try:
            return next(field for field in self._fields if field.slug == slug)
        except StopIteration:
            raise NotFoundError from None

    def has_requirements(self, pk):
        return pk in self._required_by

    def delete(self, pk):
        self.deleted.append(pk)

    def create(self, _event_id, _data):
        return self._fields[0]


class FakeCFPCategories:
    def __init__(self, categories=(), field_categories=None):
        self._categories = list(categories)
        self._field_categories = field_categories or {}
        self.links = {}

    def list_by_event(self, _event_id):
        return self._categories

    def get_personal_field_categories(self, _field_pk):
        return self._field_categories

    def set_personal_field_categories(self, field_pk, scoped):
        self.links[field_pk] = scoped


def _category(pk):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=0,
        min_participants_limit=0,
        name=f"Cat {pk}",
        pk=pk,
        slug=f"cat-{pk}",
        start_time=None,
    )


def _cfp_service(*, fields, categories=None):
    return CFPPersonalDataFieldService(
        transaction=FakeTransaction(),
        fields=fields,
        categories=categories or FakeCFPCategories(),
    )


def test_summaries_default_unused_fields_to_zero_counts():
    other = OrganizerFieldDTO(
        field_type="text", name="Phone", order=1, pk=6, question="?", slug="phone"
    )
    service = _cfp_service(
        fields=FakeCFPFields(
            fields=[_field(), other], usage={5: {"required": 2, "optional": 1}}
        )
    )

    summaries = service.list_summaries(10)

    assert [(s.field.pk, s.required_count, s.optional_count) for s in summaries] == [
        (5, 2, 1),
        (6, 0, 0),
    ]


def test_form_contexts_split_categories_by_requirement():
    categories = FakeCFPCategories(
        categories=[_category(1), _category(2), _category(3)],
        field_categories={1: True, 2: False},
    )
    service = _cfp_service(
        fields=FakeCFPFields(fields=[_field()]), categories=categories
    )

    create_context = service.get_create_form_context(10)
    edit_context = service.get_edit_form_context(10, "vegan")

    assert [c.pk for c in create_context.categories] == [1, 2, 3]
    assert edit_context.field == _field()
    assert edit_context.required_category_pks == {1}
    assert edit_context.optional_category_pks == {2}


def test_create_links_categories_through_the_personal_field_table():
    categories = FakeCFPCategories(categories=[_category(1)])
    fields = FakeCFPFields(fields=[_field()])
    service = _cfp_service(fields=fields, categories=categories)

    service.create(
        event_pk=10,
        data={"name": "Vegan"},
        category_requirements=RequirementSelectionDTO(
            requirements={1: True, 9: True}, order=[]
        ),
    )

    assert categories.links == {5: {1: True}}


def test_delete_refuses_a_field_some_category_requires():
    fields = FakeCFPFields(fields=[_field()], required_by=[5])

    assert _cfp_service(fields=fields).delete(10, "vegan") is False
    assert not fields.deleted


def test_delete_removes_an_unused_field():
    fields = FakeCFPFields(fields=[_field()])

    assert _cfp_service(fields=fields).delete(10, "vegan") is True
    assert fields.deleted == [5]


def test_delete_surfaces_an_unknown_slug():
    with pytest.raises(NotFoundError):
        _cfp_service(fields=FakeCFPFields()).delete(10, "ghost")


def test_deletion_and_restore_log_mirror_each_other():
    logs = FakeChangeLogs()

    log_facilitator_deletion(
        repo=logs, event_id=10, facilitator_id=1, user_id=None, deleted=True
    )
    log_facilitator_deletion(
        repo=logs, event_id=10, facilitator_id=1, user_id=None, deleted=False
    )

    assert [entry["changes"][0] for entry in logs.created] == [
        {"field": "deleted", "field_id": None, "old": "", "new": "yes"},
        {"field": "deleted", "field_id": None, "old": "yes", "new": ""},
    ]
