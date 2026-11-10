from datetime import UTC, datetime

from ludamus.mills.party_history import PartySessionHistoryService
from ludamus.pacts.party import PartyDTO
from ludamus.pacts.session_cards import PartyDetailDTO, PartyEventHistoryDTO
from tests.unit.factories import FakeTransaction

VIEWER_PK = 1
OUTSIDER_PK = 2
MEMBER_PK = 3
PARTY_PK = 7


def _party(*, is_leader=True):
    return PartyDTO(
        pk=PARTY_PK,
        name="Ekipa",
        leader_pk=VIEWER_PK,
        leader_name="Lena",
        is_leader=is_leader,
        is_active_member=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        members=[],
        enrolls_together=True,
    )


def _event_history():
    return PartyEventHistoryDTO(
        event_pk=3, event_name="Con", event_slug="con", sessions=[]
    )


class FakeParties:
    def __init__(self):
        self.enrollment_reads = 0

    @staticmethod
    def read_for_viewer(*, party_pk, viewer_pk):
        if (party_pk, viewer_pk) == (PARTY_PK, VIEWER_PK):
            return _party()
        if (party_pk, viewer_pk) == (PARTY_PK, MEMBER_PK):
            return _party(is_leader=False)
        return None

    def has_enrollments(self, *, leader_pk, party_pk):
        self.enrollment_reads += 1
        return (party_pk, leader_pk) == (PARTY_PK, VIEWER_PK)


class FakeHistory:
    def __init__(self):
        self.reads = 0

    def list_for_party(self, *, party_pk, viewer_pk):
        self.reads += 1
        assert party_pk == PARTY_PK
        assert viewer_pk in {VIEWER_PK, MEMBER_PK}
        return [_event_history()]


def _service(history, parties=None):
    return PartySessionHistoryService(
        transaction=FakeTransaction(), parties=parties or FakeParties(), history=history
    )


def test_member_sees_party_with_its_history():
    detail = _service(FakeHistory()).read_detail(party_pk=PARTY_PK, viewer_pk=VIEWER_PK)

    assert detail == PartyDetailDTO(
        party=_party(), history=[_event_history()], enrolling_locked=True
    )


def test_member_is_not_locked_out_and_enrollments_are_not_read():
    parties = FakeParties()

    detail = _service(FakeHistory(), parties).read_detail(
        party_pk=PARTY_PK, viewer_pk=MEMBER_PK
    )

    assert detail == PartyDetailDTO(
        party=_party(is_leader=False),
        history=[_event_history()],
        enrolling_locked=False,
    )
    assert parties.enrollment_reads == 0


def test_outsider_gets_nothing_and_history_is_not_read():
    history = FakeHistory()

    detail = _service(history).read_detail(party_pk=PARTY_PK, viewer_pk=OUTSIDER_PK)

    assert detail is None
    assert history.reads == 0
