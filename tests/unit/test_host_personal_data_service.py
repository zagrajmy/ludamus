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
from ludamus.pacts.fields import FieldTypeSwitchError
from ludamus.pacts.legacy import FacilitatorChangeLogDTO
from tests.unit.factories import FakeTransaction

EVENT_ID = 10
FACILITATOR_ID = 1


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
        self._existing = {(FACILITATOR_ID, EVENT_ID): existing or {}}
        self._existing_field_ids = {
            (FACILITATOR_ID, EVENT_ID): list(existing_field_ids)
        }

    def save(self, entries):
        self.saved.append(entries)

    def read_for_facilitator_event(self, facilitator_id, event_id):
        return dict(self._existing.get((facilitator_id, event_id), {}))

    def list_field_ids_for_facilitator_event(self, facilitator_id, event_id):
        return list(self._existing_field_ids.get((facilitator_id, event_id), []))


class FakePersonalDataFields:
    def __init__(self, fields=()):
        self._fields = {EVENT_ID: list(fields)}

    def list_by_event(self, event_id):
        return self._fields.get(event_id, [])


class FakeChangeLogs:
    def __init__(self):
        self.created = []

    def create(self, data):
        self.created.append(data)


def _facilitator(event_id=EVENT_ID):
    return FacilitatorDTO(
        accreditation_type="none",
        display_name="Alice",
        event_id=event_id,
        pk=FACILITATOR_ID,
        slug="alice",
        user_id=None,
    )


def _field():
    return OrganizerFieldDTO(
        field_type="checkbox", name="Vegan", order=0, pk=5, question="?", slug="vegan"
    )


def _phone_field():
    return OrganizerFieldDTO(
        field_type="text", name="Phone", order=1, pk=6, question="?", slug="phone"
    )


def _entry(*, value=True, field_id=5):
    return PersonalDataFieldValueData(
        facilitator_id=FACILITATOR_ID, event_id=EVENT_ID, field_id=field_id, value=value
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
    logs = FakeChangeLogs()
    repo = FakePersonalDataFieldValue(existing={"vegan": "yes"}, existing_field_ids=[5])
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10, facilitator_id=1, entries=[_entry(value="")], user_id=7
    )

    assert repo.saved == [[_entry(value="")]]
    assert logs.created == [
        {
            "event_id": 10,
            "facilitator_id": 1,
            "user_id": 7,
            "changes": [{"field": "", "field_id": 5, "old": "yes", "new": ""}],
        }
    ]


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
    data = {
        "accreditation_type": "honorary",
        "internal_comment": "VIP",
        "is_collective": True,
    }

    service.update_facilitator(
        event_id=10,
        facilitator_id=1,
        data=data,
        entries=[_entry(value=True)],
        user_id=7,
    )

    assert facilitators.updated == [(1, data)]
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
                {
                    "field": "internal_comment",
                    "field_id": None,
                    "old": "",
                    "new": "VIP",
                },
                {"field": "is_collective", "field_id": None, "old": False, "new": True},
            ],
        }
    ]


def test_update_facilitator_blank_answer_clears_a_field_that_has_one():
    repo = FakePersonalDataFieldValue(existing={"vegan": "yes"}, existing_field_ids=[5])
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=repo,
        fields=[_field()],
    )

    service.update_facilitator(
        event_id=10,
        facilitator_id=1,
        data={"accreditation_type": "none"},
        entries=[_entry(value="")],
    )

    assert repo.saved == [[_entry(value="")]]


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
        entries=[_entry(value="yes"), _entry(field_id=404, value="stray")],
    )

    assert not logs.created


def test_skipped_entries_do_not_hide_a_later_change():
    logs = FakeChangeLogs()
    service = _service(
        facilitators=FakeFacilitators(_facilitator()),
        personal_data_field_values=FakePersonalDataFieldValue(existing={}),
        fields=[_field(), _phone_field()],
        change_logs=logs,
    )

    service.update_personal_data(
        event_id=10,
        facilitator_id=1,
        entries=[
            _entry(field_id=404, value="stray"),
            _entry(field_id=6, value=""),
            _entry(value=True),
        ],
    )

    assert [entry["changes"] for entry in logs.created] == [
        [{"field": "", "field_id": 5, "old": None, "new": True}]
    ]


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
        self._entries = {EVENT_ID: entries}

    def list_by_event(self, event_id):
        return self._entries.get(event_id, [])


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
    def __init__(self, *, fields=(), answers=None, answered=()):
        self._fields = {EVENT_ID: list(fields)}
        self._answers = {EVENT_ID: answers or {}}
        self._answered = set(answered)
        self.updated = {}
        self.deleted = []

    def list_by_event(self, event_id):
        return self._fields.get(event_id, [])

    def count_values(self, event_id):
        return self._answers.get(event_id, {})

    def read_by_slug(self, event_id, slug):
        try:
            return next(
                field for field in self.list_by_event(event_id) if field.slug == slug
            )
        except StopIteration:
            raise NotFoundError from None

    def has_values(self, pk):
        return pk in self._answered

    def update(self, pk, data):
        self.updated[pk] = data

    def delete(self, pk):
        self.deleted.append(pk)

    def set_field_type(self, pk, field_type):
        fields = self._fields[EVENT_ID]
        index = next(i for i, field in enumerate(fields) if field.pk == pk)
        switched = fields[index].model_copy(update={"field_type": field_type})
        fields[index] = switched
        return switched


def _cfp_service(fields):
    return CFPPersonalDataFieldService(transaction=FakeTransaction(), fields=fields)


def test_summaries_default_unanswered_fields_to_zero():
    service = _cfp_service(
        FakeCFPFields(fields=[_field(), _phone_field()], answers={5: 3})
    )

    summaries = service.list_summaries(10)

    assert [(s.field.pk, s.answer_count) for s in summaries] == [(5, 3), (6, 0)]


def test_update_writes_against_the_pk_the_slug_resolved_to():
    fields = FakeCFPFields(fields=[_field()])

    _cfp_service(fields).update(
        event_pk=10, field_slug="vegan", data={"name": "Vegan?"}
    )

    assert fields.updated == {5: {"name": "Vegan?"}}


def test_delete_refuses_a_field_people_have_answered():
    fields = FakeCFPFields(fields=[_field()], answered=[5])

    assert _cfp_service(fields).delete(10, "vegan") is False
    assert not fields.deleted


def test_delete_removes_an_unanswered_field():
    fields = FakeCFPFields(fields=[_field()])

    assert _cfp_service(fields).delete(10, "vegan") is True
    assert fields.deleted == [5]


def test_delete_surfaces_an_unknown_slug():
    with pytest.raises(NotFoundError):
        _cfp_service(FakeCFPFields()).delete(10, "ghost")


def test_deletion_and_restore_log_mirror_each_other():
    logs = FakeChangeLogs()

    log_facilitator_deletion(
        repo=logs, event_id=10, facilitator_id=1, user_id=7, deleted=True
    )
    log_facilitator_deletion(
        repo=logs, event_id=10, facilitator_id=1, user_id=7, deleted=False
    )

    assert logs.created == [
        {
            "event_id": 10,
            "facilitator_id": 1,
            "user_id": 7,
            "changes": [
                {"field": "deleted", "field_id": None, "old": "", "new": "yes"}
            ],
        },
        {
            "event_id": 10,
            "facilitator_id": 1,
            "user_id": 7,
            "changes": [
                {"field": "deleted", "field_id": None, "old": "yes", "new": ""}
            ],
        },
    ]


def _text_field(field_type="text"):
    return OrganizerFieldDTO(
        field_type=field_type, name="Discord", order=0, pk=7, question="?", slug="dc"
    )


def _update_data():
    return {
        "name": "Discord",
        "question": "?",
        "max_length": 50,
        "help_text": "",
        "is_public": False,
        "options": None,
        "is_multiple": False,
        "allow_custom": False,
    }


def test_update_switches_a_text_field_to_discord_alongside_the_edit():
    fields = FakeCFPFields(fields=[_text_field()])

    _cfp_service(fields=fields).update(
        event_pk=10, field_slug="dc", data=_update_data(), field_type="discord"
    )

    assert fields.read_by_slug(10, "dc").field_type == "discord"
    assert list(fields.updated) == [7]


def test_update_refuses_to_switch_a_select_field_and_writes_nothing():
    fields = FakeCFPFields(fields=[_text_field("select")])

    with pytest.raises(FieldTypeSwitchError):
        _cfp_service(fields=fields).update(
            event_pk=10, field_slug="dc", data=_update_data(), field_type="discord"
        )

    assert fields.read_by_slug(10, "dc").field_type == "select"
    assert not fields.updated


def test_set_field_type_keeps_a_field_already_of_that_type():
    field = _text_field("discord")

    assert (
        _cfp_service(fields=FakeCFPFields(fields=[field])).set_field_type(
            event_pk=10, field_slug="dc", field_type="discord"
        )
        == field
    )


def test_set_field_type_switches_discord_back_to_text():
    fields = FakeCFPFields(fields=[_text_field("discord")])

    switched = _cfp_service(fields=fields).set_field_type(
        event_pk=10, field_slug="dc", field_type="text"
    )

    assert switched.field_type == "text"


def test_update_without_a_type_leaves_the_type_alone():
    fields = FakeCFPFields(fields=[_text_field("select")])

    _cfp_service(fields=fields).update(
        event_pk=10, field_slug="dc", data=_update_data()
    )

    assert fields.read_by_slug(10, "dc").field_type == "select"
    assert list(fields.updated) == [7]
