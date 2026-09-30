from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.party_history import PartySessionHistoryService
from ludamus.pacts.chronology import PartyDetailDTO, PartyEventHistoryDTO
from ludamus.pacts.party import PartyDTO

VIEWER_PK = 1
OUTSIDER_PK = 2
PARTY_PK = 7


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


def _party():
    return PartyDTO(
        pk=PARTY_PK,
        name="Ekipa",
        leader_pk=VIEWER_PK,
        leader_name="Lena",
        is_leader=True,
        is_active_member=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        members=[],
    )


def _event_history():
    return PartyEventHistoryDTO(
        event_pk=3, event_name="Con", event_slug="con", sessions=[]
    )


class FakeParties:
    @staticmethod
    def read_for_viewer(*, party_pk, viewer_pk):
        if (party_pk, viewer_pk) == (PARTY_PK, VIEWER_PK):
            return _party()
        return None


class FakeHistory:
    def __init__(self):
        self.reads = 0

    def list_for_party(self, *, party_pk, viewer_pk):
        self.reads += 1
        assert (party_pk, viewer_pk) == (PARTY_PK, VIEWER_PK)
        return [_event_history()]


def _service(history):
    return PartySessionHistoryService(
        transaction=FakeTransaction(), parties=FakeParties(), history=history
    )


def test_member_sees_party_with_its_history():
    detail = _service(FakeHistory()).read_detail(party_pk=PARTY_PK, viewer_pk=VIEWER_PK)

    assert detail == PartyDetailDTO(party=_party(), history=[_event_history()])


def test_outsider_gets_nothing_and_history_is_not_read():
    history = FakeHistory()

    detail = _service(history).read_detail(party_pk=PARTY_PK, viewer_pk=OUTSIDER_PK)

    assert detail is None
    assert history.reads == 0
