from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    OfferDTO,
    OfferRecipientDTO,
    PromotionStateDTO,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_SESSION_ID = 42
_MANAGER_ID = 99


pytestmark = pytest.mark.usefixtures("_frozen")


@pytest.fixture
def _frozen(monkeypatch):
    monkeypatch.setattr("ludamus.mills.enrollment._now", lambda: _NOW)
    monkeypatch.setattr("ludamus.mills.enrollment._token", lambda: "tok-xyz")


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, states=None, offer=None):
        self._states = list(states or [])
        self._offer = offer
        self.offered: list[dict] = []
        self.claimed: list[list[int]] = []
        self.dropped: list[list[int]] = []

    @staticmethod
    def read_offer_claim_window(_session_id):
        return timedelta(hours=24)

    def lock_and_read_state(self, _session_id):
        return self._states.pop(0) if self._states else None

    def confirm(self, ids):
        pass

    def offer(self, ids, *, offer_expires_at, claim_token, **_kwargs):
        self.offered.append({"ids": ids, "token": claim_token, "exp": offer_expires_at})

    def read_offer_by_token(self, _token):
        return self._offer

    def read_offer_by_participation(self, _participation_id):
        return self._offer

    def mark_claimed(self, ids, **_kwargs):
        self.claimed.append(ids)

    def drop(self, ids):
        self.dropped.append(ids)


class FakeNotifier:
    def __init__(self):
        self.offered = []
        self.expired = []

    def notify_offered(self, n):
        self.offered.append(n)

    def notify_offer_expired(self, n):
        self.expired.append(n)


class FakeScheduler:
    def schedule_expiry(self, *, participation_id, run_at):
        pass


def _wp(pid, *, sponsor_id=None, party_id=None, order=0):
    return WaitingParticipantDTO(
        participation_id=pid,
        user_id=pid,
        party_id=party_id,
        sponsor_id=sponsor_id,
        full_name=f"user-{pid}",
        email=f"u{pid}@example.com",
        creation_time=_NOW + timedelta(minutes=order),
        has_conflict=False,
        owner_slots_remaining=UNLIMITED_SLOTS,
        recipient_user_id=sponsor_id if sponsor_id is not None else pid,
        recipient_email=f"r{sponsor_id if sponsor_id is not None else pid}@e.com",
    )


def _state(waiting, *, mode=PromotionMode.AUTO, seats=1):
    return PromotionStateDTO(
        session_id=_SESSION_ID,
        session_title="Dragons",
        event_slug="con",
        promotion_mode=mode,
        offer_claim_window=timedelta(hours=24),
        presenter_id=None,
        available_seats=seats,
        waiting=waiting,
    )


def _build(states=None, offer=None):
    repo = FakeRepo(states=states, offer=offer)
    notifier = FakeNotifier()
    scheduler = FakeScheduler()
    service = WaitlistPromotionService(FakeTransaction(), repo, notifier, scheduler)
    return service, repo, notifier, scheduler


def _offer(*, expires):
    return OfferDTO(
        session_id=_SESSION_ID,
        session_title="Dragons",
        event_slug="con",
        participant_ids=[1, 2],
        recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
        offer_expires_at=expires,
    )


class TestFillFreedSeats:
    def test_offer_notifies_manager_for_managed_party(self):
        party = [
            _wp(1, sponsor_id=_MANAGER_ID, order=0),
            _wp(2, sponsor_id=_MANAGER_ID, order=1),
        ]
        service, repo, notifier, _ = _build(
            states=[_state(party, mode=PromotionMode.OFFER_CLAIM, seats=2)]
        )

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.offered == [1, 2]
        assert repo.offered[0]["ids"] == [1, 2]
        assert notifier.offered[0].recipient_user_id == _MANAGER_ID


class TestClaimOffer:
    def test_past_deadline_rejected(self):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW - timedelta(minutes=1)))

        result = service.claim_offer(token="tok-xyz")

        assert result.success is False
        assert result.reason == "expired"
        assert not repo.claimed


class TestExpireOffer:
    def test_not_yet_due_is_noop(self):
        service, repo, notifier, _ = _build(
            offer=_offer(expires=_NOW + timedelta(hours=1))
        )

        service.expire_offer(participation_id=1)

        assert not repo.dropped
        assert not notifier.expired
