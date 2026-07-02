from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Notification,
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
    User,
)
from ludamus.inits.services import Services
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _url(agenda_item):
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={
            "event_slug": agenda_item.session.event.slug,
            "session_id": agenda_item.session.pk,
        },
    )


def _led_party_with_member(leader, *, consent):
    member = UserFactory(
        username="member", name="Mira Member", email="mira@example.com"
    )
    party = Party.objects.create(leader=leader, name="Ekipa")
    PartyMembership.objects.create(party=party, member=leader)
    PartyMembership.objects.create(
        party=party,
        member=member,
        consent_mode=consent,
        status=PartyMembershipStatus.ACTIVE,
    )
    return party, member


def _reassign_presenter(agenda_item):
    agenda_item.session.presenter = UserFactory(username="host", name="Host")
    agenda_item.session.save()


class TestDirectEnrollmentWithPowerOfAttorney:
    @pytest.mark.usefixtures("enrollment_config")
    def test_get_offers_full_choices_for_trusting_member(
        self, authenticated_client, active_user, agenda_item
    ):
        _led_party_with_member(active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT)

        response = authenticated_client.get(_url(agenda_item))

        content = response.content.decode()
        assert "Mira Member" in content
        assert "Hold a seat" not in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_enrolls_member_directly_and_notifies(
        self, authenticated_client, active_user, agenda_item
    ):
        party, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )

        expected = f"Enrolled: {member.name}"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/chronology/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, expected)],
        )
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.CONFIRMED
        assert participation.party_id == party.pk
        notification = Notification.objects.get(recipient=member)
        assert notification.kind == NotificationKind.PARTY_ENROLLED
        assert active_user.name in notification.title


class TestHeldSeatForConsentingMember:
    @pytest.mark.usefixtures("enrollment_config")
    def test_get_offers_only_held_seat_choice(
        self, authenticated_client, active_user, agenda_item
    ):
        _led_party_with_member(active_user, consent=PartyConsentMode.ACCEPT_INVITES)

        response = authenticated_client.get(_url(agenda_item))

        content = response.content.decode()
        assert "Mira Member" in content
        assert "Hold a seat — they confirm" in content
        member = User.objects.get(username="member")
        assert f'id="user_{member.pk}_waitlist"' not in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_holds_offered_seat_and_notifies(
        self, authenticated_client, active_user, agenda_item
    ):
        party, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/chronology/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Seat held (they confirm): {member.name}")],
        )
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.OFFERED
        assert participation.party_id == party.pk
        assert participation.claim_token
        assert participation.offer_expires_at is not None
        notification = Notification.objects.get(recipient=member)
        assert notification.kind == NotificationKind.PARTY_SEAT_HELD
        assert participation.claim_token in notification.url

    @pytest.mark.usefixtures("enrollment_config")
    def test_member_claims_held_seat(
        self, authenticated_client, client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)
        authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )
        participation = SessionParticipation.objects.get(user=member)

        response = client.post(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED
        # The test client is shared with the leader's earlier POST, so its
        # flash is still queued ahead of the claim confirmation.
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:chronology:event", kwargs={"slug": agenda_item.session.event.slug}
            ),
            messages=[
                (messages.SUCCESS, "Seat held (they confirm): Mira Member"),
                (
                    messages.SUCCESS,
                    "Spot claimed — you are now confirmed for this session.",
                ),
            ],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_lapsed_held_seat_releases_only_their_seat(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)
        authenticated_client.post(
            _url(agenda_item),
            data={f"user_{active_user.pk}": "enroll", f"user_{member.pk}": "enroll"},
        )
        held = SessionParticipation.objects.get(user=member)
        SessionParticipation.objects.filter(pk=held.pk).update(
            offer_expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )

        Services().waitlist_promotion.expire_offer(participation_id=held.pk)

        assert not SessionParticipation.objects.filter(pk=held.pk).exists()
        mine = SessionParticipation.objects.get(user=active_user)
        assert mine.status == SessionParticipationStatus.CONFIRMED

    @pytest.mark.usefixtures("enrollment_config")
    def test_member_with_own_participation_is_left_alone(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=member,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.get(_url(agenda_item))

        content = response.content.decode()
        # No action radios for a member who handles their own enrollment.
        assert f'id="user_{member.pk}_enroll"' not in content
        assert f'id="user_{member.pk}_cancel"' not in content
        assert response.status_code == HTTPStatus.OK
