from contextlib import contextmanager

import pytest

from ludamus.mills.submissions.personal_data_fields import PersonalDataFieldValueService
from ludamus.pacts import (
    FacilitatorDTO,
    NotFoundError,
    PersonalDataFieldDTO,
    PersonalDataFieldValueData,
)
from ludamus.pacts.submissions import FacilitatorCreateData

_USER_ID = 7


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def atomic(self):
        return _atomic()


class FakeFacilitators:
    def __init__(self, facilitator, *, taken_slugs=()):
        self._facilitator = facilitator
        self.updated = []
        self.created = []
        self._taken = list(taken_slugs)

    def read(self, pk):
        if self._facilitator is None or self._facilitator.pk != pk:
            raise NotFoundError
        return self._facilitator

    def update(self, pk, data):
        self.updated.append((pk, data))

    def slug_exists(self, _event_id, slug):
        return slug in self._taken

    def create(self, data):
        self.created.append(data)
        return FacilitatorDTO(
            accreditation_type=data["accreditation_type"],
            display_name=data["display_name"],
            event_id=data["event_id"],
            pk=99,
            slug=data["slug"],
            user_id=data.get("user_id"),
        )


class FakePersonalDataFieldValue:
    def __init__(self, existing=None):
        self.saved = []
        self._existing = existing or {}

    def save(self, entries):
        self.saved.append(entries)

    def read_for_facilitator_event(self, _facilitator_id, _event_id):
        return dict(self._existing)


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


def _facilitator(pk=1, event_id=10, accreditation_type="none"):
    return FacilitatorDTO(
        accreditation_type=accreditation_type,
        display_name="Alice",
        event_id=event_id,
        pk=pk,
        slug="alice",
        user_id=None,
    )


def _field(pk=5, slug="vegan"):
    return PersonalDataFieldDTO(
        field_type="checkbox", name="Vegan", order=0, pk=pk, question="?", slug=slug
    )


def _entry(*, facilitator_id=1, event_id=10, field_id=5, value=True):
    return PersonalDataFieldValueData(
        facilitator_id=facilitator_id, event_id=event_id, field_id=field_id, value=value
    )


def _service(*, facilitators, personal_data_field_values, fields=(), change_logs=None):
    return PersonalDataFieldValueService(
        transaction=FakeTransaction(),
        facilitators=facilitators,
        personal_data_field_values=personal_data_field_values,
        personal_data_fields=FakePersonalDataFields(fields),
        facilitator_change_logs=change_logs or FakeChangeLogs(),
    )


def test_saves_entries_when_facilitator_belongs_to_event():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
    )

    service.update_personal_data(event_id=10, facilitator_id=1, entries=[_entry()])

    assert repo.saved == [[_entry()]]


def test_rejects_facilitator_from_other_event():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator(event_id=99)),
        personal_data_field_values=repo,
    )

    with pytest.raises(NotFoundError):
        service.update_personal_data(event_id=10, facilitator_id=1, entries=[_entry()])

    assert not repo.saved


def test_create_facilitator_uniquifies_a_colliding_slug():
    facilitators = FakeFacilitators(_facilitator(), taken_slugs=["alice"])
    service = _service(
        facilitators=facilitators,
        personal_data_field_values=FakePersonalDataFieldValue(),
    )

    result = service.create_facilitator(
        event_id=10,
        data=FacilitatorCreateData(
            display_name="Alice", base_slug="alice", accreditation_type="none"
        ),
    )

    assert result.slug != "alice"
    assert result.slug.startswith("alice-")
    assert facilitators.created[0]["slug"] == result.slug


def test_empty_entries_skips_save():
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()), personal_data_field_values=repo
    )

    service.update_personal_data(event_id=10, facilitator_id=1, entries=[])

    assert not repo.saved


def test_personal_data_change_is_logged():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={}),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value=True)], user_id=_USER_ID
    )

    assert len(logs.created) == 1
    entry = logs.created[0]
    assert entry["facilitator_id"] == 1
    assert entry["user_id"] == _USER_ID
    assert {"field": "", "field_id": 5, "old": None, "new": True} in entry["changes"]


def test_unchanged_personal_data_logs_nothing():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={"vegan": True}),
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value=True)]
    )

    assert not logs.created


def test_entry_for_unknown_field_is_ignored():
    logs = FakeChangeLogs()
    repo = FakePersonalDataFieldValue()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field(pk=5)],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(field_id=999, value=True)]
    )

    assert repo.saved == [[_entry(field_id=999, value=True)]]
    assert not logs.created


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


def test_update_facilitator_logs_accreditation_change():
    logs = FakeChangeLogs()
    facilitators = FakeFacilitators(_facilitator(accreditation_type="none"))
    service = _service(
        facilitators=facilitators,
        personal_data_field_values=FakePersonalDataFieldValue(),
        change_logs=logs,
    )

    service.update_facilitator(
        event_id=10,
        facilitator_id=1,
        data={
            "accreditation_type": "honorary",
            "internal_comment": "Possible duplicate",
        },
        entries=[],
        user_id=_USER_ID,
    )

    assert facilitators.updated == [
        (
            1,
            {
                "accreditation_type": "honorary",
                "internal_comment": "Possible duplicate",
            },
        )
    ]
    assert {
        "field": "accreditation_type",
        "field_id": None,
        "old": "none",
        "new": "honorary",
    } in logs.created[0]["changes"]


def test_update_facilitator_logs_internal_comment_change():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(),
        change_logs=logs,
    )

    service.update_facilitator(
        event_id=10,
        facilitator_id=1,
        data={"accreditation_type": "none", "internal_comment": "Possible duplicate"},
        entries=[],
        user_id=_USER_ID,
    )

    assert logs.created[0]["changes"] == [
        {
            "field": "internal_comment",
            "field_id": None,
            "old": "",
            "new": "Possible duplicate",
        }
    ]
