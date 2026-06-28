from contextlib import contextmanager

import pytest

from ludamus.mills.submissions.personal_data_fields import HostPersonalDataService
from ludamus.pacts import FacilitatorDTO, HostPersonalDataEntry, NotFoundError


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def atomic(self):
        return _atomic()


class FakeFacilitators:
    def __init__(self, facilitator):
        self._facilitator = facilitator

    def read(self, pk):
        if self._facilitator is None or self._facilitator.pk != pk:
            raise NotFoundError
        return self._facilitator


class FakeHostPersonalData:
    def __init__(self):
        self.saved = []

    def save(self, entries):
        self.saved.append(entries)


def _facilitator(pk=1, event_id=10):
    return FacilitatorDTO(
        accreditation_type="none",
        display_name="Alice",
        event_id=event_id,
        pk=pk,
        slug="alice",
        user_id=None,
    )


def _entry(facilitator_id=1, event_id=10):
    return HostPersonalDataEntry(
        facilitator_id=facilitator_id, event_id=event_id, field_id=5, value=True
    )


def test_saves_entries_when_facilitator_belongs_to_event():
    repo = FakeHostPersonalData()
    service = HostPersonalDataService(
        transaction=FakeTransaction(),
        facilitators=FakeFacilitators(_facilitator()),
        host_personal_data=repo,
    )

    service.update_personal_data(event_id=10, facilitator_id=1, entries=[_entry()])

    assert repo.saved == [[_entry()]]


def test_rejects_facilitator_from_other_event():
    repo = FakeHostPersonalData()
    service = HostPersonalDataService(
        transaction=FakeTransaction(),
        facilitators=FakeFacilitators(_facilitator(event_id=99)),
        host_personal_data=repo,
    )

    with pytest.raises(NotFoundError):
        service.update_personal_data(event_id=10, facilitator_id=1, entries=[_entry()])

    assert not repo.saved


def test_empty_entries_skips_save():
    repo = FakeHostPersonalData()
    service = HostPersonalDataService(
        transaction=FakeTransaction(),
        facilitators=FakeFacilitators(_facilitator()),
        host_personal_data=repo,
    )

    service.update_personal_data(event_id=10, facilitator_id=1, entries=[])

    assert not repo.saved
