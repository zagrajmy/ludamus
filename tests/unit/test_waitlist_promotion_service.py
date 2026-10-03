import re
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    ClaimResult,
    HeldSeatData,
    OfferDTO,
    OfferRecipientDTO,
    PromotionResult,
    PromotionStateDTO,
    SeatHoldRequest,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode
from tests.unit.factories import FakeTransaction

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_SESSION_ID = 42
_MANAGER_ID = 99
_HELD_ID = 77
_CLAIM_WINDOW = timedelta(hours=24)
_URL_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_-]{64}")


pytestmark = pytest.mark.usefixtures("_frozen")


@pytest.fixture
def _frozen(monkeypatch):
    monkeypatch.setattr("ludamus.mills.enrollment._now", lambda: _NOW)
    monkeypatch.setattr("ludamus.mills.enrollment._token", lambda: "tok-xyz")


class FakeRepo:
    def __init__(self, states=None, offer=None, lapsed=()):
        self._seed = {
            "states": list(states or []),
            "offer": offer,
            "lapsed": list(lapsed),
        }
        self.confirmed: list[list[int]] = []
        self.offered: list[dict] = []
        self.held: list[HeldSeatData] = []
        self.claimed: list[list[int]] = []
        self.dropped: list[list[int]] = []

    @staticmethod
    def read_offer_claim_window(_session_id):
        return timedelta(hours=24)

    def lock_and_read_state(self, _session_id):
        return self._seed["states"].pop(0) if self._seed["states"] else None

    def confirm(self, ids):
        self.confirmed.append(ids)

    def create_offered(self, seat):
        self.held.append(seat)
        return _HELD_ID

    def list_lapsed_offers(self, _now):
        return list(self._seed["lapsed"])

    def offer(self, ids, *, offer_expires_at, claim_token, **_kwargs):
        self.offered.append({"ids": ids, "token": claim_token, "exp": offer_expires_at})

    def read_offer_by_token(self, _token):
        return self._seed["offer"]

    def read_offer_for_member(self, *, user_id, session_id):
        del user_id
        return self._seed["offer"] if session_id == _SESSION_ID else None

    def read_offer_by_participation(self, _participation_id):
        return self._seed["offer"]

    def mark_claimed(self, ids, **_kwargs):
        self.claimed.append(ids)

    def drop(self, ids):
        self.dropped.append(ids)


class FakeNotifier:
    def __init__(self):
        self.promoted = []
        self.offered = []
        self.expired = []
        self.held = []

    def notify_promoted(self, n):
        self.promoted.append(n)

    def notify_offered(self, n):
        self.offered.append(n)

    def notify_offer_expired(self, n):
        self.expired.append(n)

    def notify_seat_held(self, n):
        self.held.append(n)


class FakeScheduler:
    def __init__(self):
        self.scheduled: list[tuple[int, datetime]] = []

    def schedule_expiry(self, *, participation_id, run_at):
        self.scheduled.append((participation_id, run_at))


def _wp(pid, *, sponsor_id=None, order=0):
    return WaitingParticipantDTO(
        participation_id=pid,
        user_id=pid,
        party_id=None,
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


def _build(states=None, offer=None, lapsed=()):
    repo = FakeRepo(states=states, offer=offer, lapsed=lapsed)
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


class TestExpireOffer:
    def test_not_yet_due_is_noop(self):
        service, repo, notifier, _ = _build(
            offer=_offer(expires=_NOW + timedelta(hours=1))
        )

        service.expire_offer(participation_id=1)

        assert not repo.dropped
        assert not notifier.expired


class TestFillFreedSeatsOutcomes:
    def test_a_gone_or_unscheduled_session_promotes_nobody(self):
        service, repo, notifier, _ = _build(states=[])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result == PromotionResult()
        assert not repo.confirmed
        assert not notifier.promoted

    def test_no_free_seat_promotes_nobody(self):
        service, repo, notifier, _ = _build(states=[_state([_wp(1)], seats=0)])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result == PromotionResult()
        assert not repo.confirmed
        assert not notifier.promoted

    def test_auto_mode_confirms_and_tells_the_waiter(self):
        service, repo, notifier, scheduler = _build(states=[_state([_wp(1)])])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.promoted == [1]
        assert repo.confirmed == [[1]]
        assert [n.recipient_user_id for n in notifier.promoted] == [1]
        assert notifier.promoted[0].event_slug == "con"
        assert not scheduler.scheduled

    def test_offer_mode_arms_one_expiry_per_party(self):
        service, repo, notifier, scheduler = _build(
            states=[_state([_wp(1), _wp(2, order=1)], mode=PromotionMode.OFFER_CLAIM)]
        )

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.offered == [1]
        assert repo.offered == [
            {"ids": [1], "token": "tok-xyz", "exp": _NOW + _CLAIM_WINDOW}
        ]
        assert notifier.offered[0].offer_expires_at == _NOW + _CLAIM_WINDOW
        assert scheduler.scheduled == [(1, _NOW + _CLAIM_WINDOW)]

    def test_a_fresh_claim_token_is_long_and_url_safe(self, monkeypatch):
        monkeypatch.undo()
        service, repo, _, _ = _build(
            states=[_state([_wp(1)], mode=PromotionMode.OFFER_CLAIM)]
        )

        service.fill_freed_seats(session_id=_SESSION_ID)

        assert _URL_SAFE_TOKEN.fullmatch(repo.offered[0]["token"])


def _hold():
    return SeatHoldRequest(
        session_id=_SESSION_ID,
        session_title="Dragons",
        user_id=5,
        user_email="m@e.com",
        party_id=3,
        actor_name="Leader",
    )


class TestHoldSeat:
    def test_writes_an_offered_row_notifies_and_arms_expiry(self):
        service, repo, notifier, scheduler = _build()

        service.hold_seat(hold=_hold())

        assert repo.held == [
            HeldSeatData(
                session_id=_SESSION_ID,
                user_id=5,
                party_id=3,
                offered_at=_NOW,
                offer_expires_at=_NOW + _CLAIM_WINDOW,
                claim_token="tok-xyz",
            )
        ]
        assert notifier.held[0].recipient_email == "m@e.com"
        assert notifier.held[0].actor_name == "Leader"
        assert notifier.held[0].claim_token == "tok-xyz"
        assert scheduler.scheduled == [(_HELD_ID, _NOW + _CLAIM_WINDOW)]


class TestPeekOffer:
    def test_returns_the_offer_behind_the_token(self):
        offer = _offer(expires=_NOW + timedelta(hours=1))
        service, _, _, _ = _build(offer=offer)

        assert service.peek_offer(token="tok-xyz") == offer

    def test_unknown_token_is_none(self):
        service, _, _, _ = _build()

        assert service.peek_offer(token="tok-xyz") is None


_CLAIM_ROUTES = pytest.mark.parametrize(
    "claim",
    (
        pytest.param(
            lambda service: service.claim_offer(token="tok-xyz"), id="by-token"
        ),
        pytest.param(
            lambda service: service.claim_member_offer(
                user_id=_MANAGER_ID, session_id=_SESSION_ID
            ),
            id="by-member",
        ),
    ),
)


@_CLAIM_ROUTES
class TestClaimOffer:
    def test_no_offer_is_not_found(self, claim):
        service, repo, _, _ = _build()

        result = claim(service)

        assert result == ClaimResult(success=False, reason="not_found")
        assert not repo.claimed

    def test_past_deadline_is_rejected(self, claim):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW - timedelta(minutes=1)))

        result = claim(service)

        assert result == ClaimResult(
            success=False, reason="expired", session_id=_SESSION_ID, event_slug="con"
        )
        assert not repo.claimed

    def test_claims_the_whole_party_before_the_deadline(self, claim):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW + timedelta(hours=1)))

        result = claim(service)

        assert result == ClaimResult(
            success=True, session_id=_SESSION_ID, event_slug="con"
        )
        assert repo.claimed == [[1, 2]]


class TestClaimMemberOffer:
    def test_a_session_this_member_holds_no_offer_at_is_not_found(self):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW + timedelta(hours=1)))

        result = service.claim_member_offer(
            user_id=_MANAGER_ID, session_id=_SESSION_ID + 1
        )

        assert result == ClaimResult(success=False, reason="not_found")
        assert not repo.claimed


class TestDeclineOffer:
    def test_unknown_token_is_not_found(self):
        service, repo, _, _ = _build()

        result = service.decline_offer(token="tok-xyz")

        assert result == ClaimResult(success=False, reason="not_found")
        assert not repo.dropped

    def test_drops_the_party_and_rolls_the_seats_on(self):
        service, repo, notifier, _ = _build(
            states=[_state([_wp(3)], seats=2)],
            offer=_offer(expires=_NOW + timedelta(hours=1)),
        )

        result = service.decline_offer(token="tok-xyz")

        assert result == ClaimResult(
            success=True, session_id=_SESSION_ID, event_slug="con"
        )
        assert repo.dropped == [[1, 2]]
        assert repo.confirmed == [[3]]
        assert [n.recipient_user_id for n in notifier.promoted] == [3]


class TestExpireOfferOutcomes:
    def test_already_resolved_party_is_noop(self):
        service, repo, notifier, _ = _build()

        result = service.expire_offer(participation_id=1)

        assert result == PromotionResult()
        assert not repo.dropped
        assert not notifier.expired

    def test_lapsed_party_is_dropped_told_and_its_seats_roll_on(self):
        service, repo, notifier, _ = _build(
            states=[_state([_wp(3)], seats=2)],
            offer=_offer(expires=_NOW - timedelta(minutes=1)),
        )

        result = service.expire_offer(participation_id=1)

        assert repo.dropped == [[1, 2]]
        assert [n.recipient_user_id for n in notifier.expired] == [_MANAGER_ID]
        assert result.promoted == [3]


class TestExpireLapsedOffers:
    def test_expires_every_lapsed_party_and_counts_them(self):
        service, repo, _, _ = _build(
            lapsed=[1, 9], offer=_offer(expires=_NOW - timedelta(minutes=1))
        )

        count = service.expire_lapsed_offers(now=_NOW)

        assert count == len(repo.dropped)
        assert repo.dropped == [[1, 2], [1, 2]]

    def test_nothing_lapsed_expires_nothing(self):
        service, repo, _, _ = _build()

        assert service.expire_lapsed_offers(now=_NOW) == 0
        assert not repo.dropped
