from contextlib import contextmanager

import pytest

from ludamus.mills.submissions.personal_data_fields import PersonalDataFieldValueService
from ludamus.pacts import (
    FacilitatorDTO,
    NotFoundError,
    OrganizerFieldDTO,
    PersonalDataFieldValueData,
)


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
        if self._facilitator is None or self._facilitator.pk != pk:
            raise NotFoundError
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
