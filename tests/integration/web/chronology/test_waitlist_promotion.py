from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.core.management import call_command
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.enrollment import ParticipationPromotionRepository
from ludamus.links.db.django.models import (
    DomainEnrollmentConfig,
    Notification,
    Party,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.pacts.crowd import UserType
from ludamus.pacts.enrollment import OfferDTO, OfferRecipientDTO
from ludamus.pacts.legacy import NotificationKind, PromotionMode
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)
from tests.integration.utils import assert_response


def _service():
    return Services().waitlist_promotion


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestFillFreedSeats:
    def test_auto_promotes_waiter_and_notifies(
        self, session, waiter, mailoutbox, django_capture_on_commit_callbacks
    ):
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        with django_capture_on_commit_callbacks(execute=True):
            result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert result.promoted == [participation.pk]
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["waiter@example.com"]

    def test_offer_mode_holds_seat_and_notifies(
        self, session, event, waiter, mailoutbox, django_capture_on_commit_callbacks
    ):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        with django_capture_on_commit_callbacks(execute=True):
            result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.OFFERED.value
        assert participation.claim_token
        assert participation.offer_expires_at is not None
        assert result.offered == [participation.pk]
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_OFFER.value
        ).exists()
        assert len(mailoutbox) == 1

    def test_offered_seat_is_held_not_offered_twice(self, session, event, waiter):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        other = UserFactory(username="other", email="other@example.com")
        SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )
        second = SessionParticipation.objects.create(
            session=session, user=other, status=SessionParticipationStatus.WAITING
        )

        _service().fill_freed_seats(session_id=session.pk)
        # The single seat is now held by the first offer; a re-run is a no-op.
        result = _service().fill_freed_seats(session_id=session.pk)

        second.refresh_from_db()
        assert second.status == SessionParticipationStatus.WAITING.value
        assert not result.offered

    def test_promotes_within_membership_allowance(
        self, session, waiter, enrollment_config
    ):
        # Stored user + domain configs exercise the membership-slot computation.
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=waiter.email,
            allowed_slots=5,
        )
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=waiter.email.split("@")[1],
            allowed_slots_per_user=2,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert result.promoted == [participation.pk]
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_restrictive_domain_allowance_holds_seat(
        self, session, waiter, enrollment_config
    ):
        # The stored domain config grants this waiter no slots, so even a free
        # seat must not be filled — proving the membership allowance is read from
        # the configs and governs promotion (not just the seat count).
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=waiter.email.split("@")[1],
            allowed_slots_per_user=0,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert not result.promoted
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.WAITING.value

    def test_promotes_emailless_waiter_without_membership_limit(self, session):
        emailless = UserFactory(username="no-email", email="")
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=emailless, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert result.promoted == [participation.pk]
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_shadowbanned_waiter_not_promoted(self, session, waiter):
        banner = UserFactory(username="presenter", email="presenter@example.com")
        session.presenter = banner
        session.participants_limit = 1
        session.save()
        banner.shadowbanned.add(waiter)
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert not result.promoted
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.WAITING.value

    def test_promotion_respects_membership_across_distinct_parties(
        self, session, enrollment_config
    ):
        manager = UserFactory(username="slot-mgr", email="slot-mgr@example.com")
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=manager.email,
            allowed_slots=1,
        )
        party_a = Party.objects.create(leader=manager, name="A")
        party_b = Party.objects.create(leader=manager, name="B")
        members = [
            UserFactory(
                username="comp-a",
                email="comp-a@example.com",
                user_type=UserType.CONNECTED,
                manager=manager,
            ),
            UserFactory(
                username="comp-b",
                email="comp-b@example.com",
                user_type=UserType.CONNECTED,
                manager=manager,
            ),
        ]
        session.participants_limit = 5
        session.save()
        first = SessionParticipation.objects.create(
            session=session,
            user=members[0],
            party_id=party_a.pk,
            status=SessionParticipationStatus.WAITING,
        )
        second = SessionParticipation.objects.create(
            session=session,
            user=members[1],
            party_id=party_b.pk,
            status=SessionParticipationStatus.WAITING,
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert result.promoted == [first.pk]
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == SessionParticipationStatus.CONFIRMED.value
        assert second.status == SessionParticipationStatus.WAITING.value


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestOfferClaimAndExpiry:
    def _offer(self, session, event, waiter):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )
        _service().fill_freed_seats(session_id=session.pk)
        participation.refresh_from_db()
        return participation

    def test_claim_view_confirms_party(self, client, session, event, waiter):
        participation = self._offer(session, event, waiter)

        response = client.post(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Spot claimed — you are now confirmed for this session.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert participation.claimed_at is not None

    def test_claim_view_get_shows_offer(self, client, session, event, waiter):
        participation = self._offer(session, event, waiter)

        response = client.get(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/offer_claim.html",
            context_data={
                "offer": OfferDTO(
                    session_id=session.pk,
                    session_title=session.title,
                    event_slug=event.slug,
                    participant_ids=[participation.pk],
                    recipients=[
                        OfferRecipientDTO(user_id=waiter.pk, email=waiter.email)
                    ],
                    offer_expires_at=participation.offer_expires_at,
                ),
                "token": participation.claim_token,
            },
        )

    def test_claim_view_get_unknown_token_redirects(self, client):
        response = client.get(
            reverse("web:chronology:offer-claim", kwargs={"token": "nope"})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "This offer is no longer available or has expired.")
            ],
            url=reverse("web:events"),
        )

    def test_claim_view_unknown_token_redirects(self, client):
        response = client.post(
            reverse("web:chronology:offer-claim", kwargs={"token": "nope"})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "This offer has expired or was already claimed.")
            ],
            url=reverse("web:events"),
        )

    def test_decline_view_drops_offer_and_rolls_on(
        self, client, session, event, waiter
    ):
        participation = self._offer(session, event, waiter)
        next_waiter = UserFactory(username="next", email="next@example.com")
        SessionParticipation.objects.create(
            session=session, user=next_waiter, status=SessionParticipationStatus.WAITING
        )

        response = client.post(
            reverse(
                "web:chronology:offer-decline",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Offer declined — the seat was released.")],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        assert not SessionParticipation.objects.filter(pk=participation.pk).exists()
        # The freed seat rolled on: offer mode holds it for the next waiter.
        rolled = SessionParticipation.objects.get(user=next_waiter)
        assert rolled.status == SessionParticipationStatus.OFFERED.value

    def test_decline_view_unknown_token_redirects(self, client):
        response = client.post(
            reverse("web:chronology:offer-decline", kwargs={"token": "nope"})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "This offer is no longer available or has expired.")
            ],
            url=reverse("web:events"),
        )

    def test_claim_page_offers_a_decline_way_out(self, client, session, event, waiter):
        participation = self._offer(session, event, waiter)

        response = client.get(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        content = response.content.decode()
        assert "Claim my spot" in content
        assert "Decline offer" in content

    def test_expire_drops_lapsed_party_and_rolls_on(
        self, session, event, waiter, mailoutbox, django_capture_on_commit_callbacks
    ):
        participation = self._offer(session, event, waiter)
        # Force the offer past its deadline.
        participation.offer_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        participation.save()
        next_user = UserFactory(username="next", email="next@example.com")
        next_participation = SessionParticipation.objects.create(
            session=session, user=next_user, status=SessionParticipationStatus.WAITING
        )

        with django_capture_on_commit_callbacks(execute=True):
            _service().expire_offer(participation_id=participation.pk)

        assert not SessionParticipation.objects.filter(pk=participation.pk).exists()
        next_participation.refresh_from_db()
        # AUTO is not set here (still OFFER_CLAIM), so the next waiter is offered.
        assert next_participation.status == SessionParticipationStatus.OFFERED.value
        assert any(
            m.subject.startswith("Your offer") or "expired" in m.subject.lower()
            for m in mailoutbox
        )

    def test_expire_offers_command_sweeps_lapsed_offers(self, session, event, waiter):
        participation = self._offer(session, event, waiter)
        participation.offer_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        participation.save()
        next_user = UserFactory(username="cmd-next", email="cmd-next@example.com")
        next_participation = SessionParticipation.objects.create(
            session=session, user=next_user, status=SessionParticipationStatus.WAITING
        )

        call_command("expire_offers")

        assert not SessionParticipation.objects.filter(pk=participation.pk).exists()
        next_participation.refresh_from_db()
        assert next_participation.status == SessionParticipationStatus.OFFERED.value

    def test_expire_offers_command_dedups_party_by_token(self, session, waiter):
        # A party shares one claim_token; the sweep must expire it once, not once
        # per member, so the second row with the same token is skipped.
        lapsed = datetime.now(UTC) - timedelta(minutes=1)
        other = UserFactory(username="party-2", email="party-2@example.com")
        first = SessionParticipation.objects.create(
            session=session,
            user=waiter,
            status=SessionParticipationStatus.OFFERED,
            claim_token="shared-token",
            offer_expires_at=lapsed,
        )
        second = SessionParticipation.objects.create(
            session=session,
            user=other,
            status=SessionParticipationStatus.OFFERED,
            claim_token="shared-token",
            offer_expires_at=lapsed,
        )

        call_command("expire_offers")

        assert not SessionParticipation.objects.filter(pk=first.pk).exists()
        assert not SessionParticipation.objects.filter(pk=second.pk).exists()


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestPromotionRepositoryEdges:
    def test_lock_and_read_state_missing_session_returns_none(self):
        with DjangoTransaction().atomic():
            assert (
                ParticipationPromotionRepository().lock_and_read_state(9_999_999)
                is None
            )

    def test_reads_return_none_for_non_offered_participations(self, session, waiter):
        confirmed = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.CONFIRMED
        )
        repo = ParticipationPromotionRepository()
        with DjangoTransaction().atomic():
            assert repo.read_offer_by_participation(confirmed.pk) is None
            assert repo.read_offer_by_participation(9_999_999) is None
            assert repo.read_offer_by_token("no-such-token") is None

    def test_lock_and_read_state_reuses_manager_slots_within_a_party(self, session):
        # Two login-less companions sponsored by the same leader share one
        # membership-slot computation: the second reuses the first's cached
        # value. (A real user always spends their own allowance instead.)
        manager = UserFactory(username="party-mgr", email="party-mgr@example.com")
        members = [
            UserFactory(
                username="party-a",
                email="a@example.com",
                user_type=UserType.CONNECTED,
                manager=manager,
            ),
            UserFactory(
                username="party-b",
                email="b@example.com",
                user_type=UserType.CONNECTED,
                manager=manager,
            ),
        ]
        for member in members:
            SessionParticipation.objects.create(
                session=session, user=member, status=SessionParticipationStatus.WAITING
            )

        with DjangoTransaction().atomic():
            state = ParticipationPromotionRepository().lock_and_read_state(session.pk)

        assert state is not None
        assert {w.recipient_user_id for w in state.waiting} == {manager.pk}
        assert len({w.owner_slots_remaining for w in state.waiting}) == 1

    def test_slots_remaining_handles_email_without_at_sign(
        self, session, enrollment_config
    ):
        # A malformed (domainless) email skips the per-domain allowance lookup but
        # still honours a matching per-user config.
        allowed_slots = 3
        weird = UserFactory(username="weird", email="weird-no-at")
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email="weird-no-at",
            allowed_slots=allowed_slots,
        )
        SessionParticipation.objects.create(
            session=session, user=weird, status=SessionParticipationStatus.WAITING
        )

        with DjangoTransaction().atomic():
            state = ParticipationPromotionRepository().lock_and_read_state(session.pk)

        assert state is not None
        [waiting] = state.waiting
        assert waiting.owner_slots_remaining == allowed_slots


class TestPromotionRepositoryUnscheduledSession:
    def test_offer_for_unscheduled_session_uses_session_event_slug(
        self, session, waiter
    ):
        # The session has no agenda item (never scheduled), but it still belongs
        # to an event directly, so the offer carries that event's slug.
        offered = SessionParticipation.objects.create(
            session=session,
            user=waiter,
            status=SessionParticipationStatus.OFFERED,
            claim_token="tok-no-agenda",
            offer_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        with DjangoTransaction().atomic():
            offer = ParticipationPromotionRepository().read_offer_by_token(
                "tok-no-agenda"
            )

        assert offer is not None
        assert offer.event_slug == session.event.slug
        assert offer.participant_ids == [offered.pk]


# lock+select session, most-liberal config, waiting list, sponsors, batched
# conflicts, active configs, user-config __in, domain-config __in, companions +
# used slots (one config-holding owner), available-seats count, shadowban ids.
STATE_QUERIES = 12
BASE_WAITERS = 3
GROWN_WAITERS = 5


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestPromotionStateQueryCount:
    @staticmethod
    def _wait(session, user):
        return SessionParticipation.objects.create(
            session=session, user=user, status=SessionParticipationStatus.WAITING
        )

    def _add_waiters(self, *, session, enrollment_config, companions_a):
        # Owner A (holds a user config) waits themselves plus `companions_a`
        # sponsored companions; owner B (no config) waits too. Growing
        # `companions_a` adds waiters without adding slot owners.
        owner_a = UserFactory(username="qc-owner-a", email="qc-owner-a@example.com")
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=owner_a.email,
            allowed_slots=5,
        )
        owner_b = UserFactory(username="qc-owner-b", email="qc-owner-b@example.com")
        self._wait(session, owner_a)
        for index in range(companions_a):
            companion = UserFactory(
                username=f"qc-companion-{index}",
                email=f"qc-companion-{index}@example.com",
                user_type=UserType.CONNECTED,
                manager=owner_a,
            )
            self._wait(session, companion)
        self._wait(session, owner_b)

    def test_pinned_query_count(
        self, session, enrollment_config, django_assert_num_queries
    ):
        self._add_waiters(
            session=session, enrollment_config=enrollment_config, companions_a=1
        )
        repo = ParticipationPromotionRepository()

        with DjangoTransaction().atomic(), django_assert_num_queries(STATE_QUERIES):
            state = repo.lock_and_read_state(session.pk)

        assert state is not None
        assert len(state.waiting) == BASE_WAITERS

    def test_count_constant_as_waiters_grow(
        self, session, enrollment_config, django_assert_num_queries
    ):
        self._add_waiters(
            session=session, enrollment_config=enrollment_config, companions_a=3
        )
        repo = ParticipationPromotionRepository()

        with DjangoTransaction().atomic(), django_assert_num_queries(STATE_QUERIES):
            state = repo.lock_and_read_state(session.pk)

        assert state is not None
        assert len(state.waiting) == GROWN_WAITERS

    def test_conflict_flags_follow_confirmed_overlap(self, session, agenda_item):
        clashing = UserFactory(username="qc-clash", email="qc-clash@example.com")
        clear = UserFactory(username="qc-clear", email="qc-clear@example.com")
        self._wait(session, clashing)
        self._wait(session, clear)
        other_session = SessionFactory(
            event=session.event, category=None, participants_limit=10
        )
        AgendaItemFactory(
            session=other_session,
            space=agenda_item.space,
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
        )
        SessionParticipation.objects.create(
            session=other_session,
            user=clashing,
            status=SessionParticipationStatus.CONFIRMED,
        )

        with DjangoTransaction().atomic():
            state = ParticipationPromotionRepository().lock_and_read_state(session.pk)

        assert state is not None
        assert {w.user_id: w.has_conflict for w in state.waiting} == {
            clashing.pk: True,
            clear.pk: False,
        }
