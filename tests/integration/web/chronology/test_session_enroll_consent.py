from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY, Mock, patch

import pytest
from django.contrib import messages
from django.contrib.messages import get_messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Notification,
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
    User,
    UserEnrollmentConfig,
)
from ludamus.inits.services import Services
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, input_tag


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

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
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
            url=f"/event/{agenda_item.session.event.slug}/",
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

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        assert "Mira Member" in content
        # Ticking the box holds a seat the member must approve; the hint says so
        # and there is no separate waiting-list control.
        assert "needs their approval" in content
        member = User.objects.get(username="member")
        assert f'name="user_{member.pk}" value="include"' in content
        assert "waitlist" not in content

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
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[
                (
                    messages.SUCCESS,
                    f"Seat held (awaiting their approval): {member.name}",
                )
            ],
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
                (messages.SUCCESS, "Seat held (awaiting their approval): Mira Member"),
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

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = " ".join(response.content.decode().split())
        # A member who handles their own enrollment renders as a checked but
        # untoggleable row, with the reason spelled out beside it.
        tag = input_tag(content, member.pk)
        assert "checked" in tag
        assert "disabled" in tag
        assert "They manage their own enrollment" in content


class TestHeldSeatUnavailable:
    @pytest.mark.usefixtures("enrollment_config")
    def test_member_with_time_conflict_cannot_be_offered_a_seat(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        other = SessionFactory(event=agenda_item.session.event)
        AgendaItemFactory(
            session=other,
            space=SpaceFactory(event=agenda_item.session.event),
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
        )
        SessionParticipation.objects.create(
            session=other, user=member, status=SessionParticipationStatus.CONFIRMED
        )

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert "Mira Member" in content
        assert f'id="user_{member.pk}_enroll"' not in content
        assert "Time conflict" in content

    def test_hold_rejected_when_viewer_lacks_enrollment_access(
        self, staff_client, staff_user, agenda_item, enrollment_config
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        _, member = _led_party_with_member(
            staff_user, consent=PartyConsentMode.ACCEPT_INVITES
        )

        response = staff_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )

        assert response.status_code == HTTPStatus.OK
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert (
            "Mira Member cannot enroll: enrollment access permission required" in texts
        )
        assert not SessionParticipation.objects.filter(user=member).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_pending_invitee_is_not_listed(
        self, authenticated_client, active_user, agenda_item
    ):
        party, _ = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        invitee = UserFactory(username="invited", name="Iga Invited")
        PartyMembership.objects.create(
            party=party,
            member=invitee,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert "Mira Member" in content
        assert "Iga Invited" not in content

    @pytest.mark.usefixtures("enrollment_config")
    def test_race_on_a_member_who_enrolled_themselves_skips(
        self, authenticated_client, active_user, agenda_item
    ):
        # The form rejects "enroll" for a member with a participation, so the
        # in-processing guard only fires when a competing request seated the
        # member between form validation and processing — simulated here by
        # forcing the cleaned data through, as the conflict-race test does.
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=member,
            status=SessionParticipationStatus.CONFIRMED,
        )

        with patch(
            "ludamus.adapters.web.django.views.create_enrollment_form"
        ) as mock_form_factory:
            mock_form_class = Mock()
            mock_form_instance = Mock()
            mock_form_instance.is_valid.return_value = True
            mock_form_instance.cleaned_data = {f"user_{member.pk}": "enroll"}
            mock_form_class.return_value = mock_form_instance
            mock_form_factory.return_value = mock_form_class

            response = authenticated_client.post(
                _url(agenda_item), data={f"user_{member.pk}": "enroll"}
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Skipped (already enrolled or conflicts): "
                        "Mira Member (manages their own enrollment)"
                    ),
                )
            ],
        )
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.CONFIRMED
        assert Notification.objects.count() == 0


class TestMemberSeatIsTheirOwn:
    # The template dashes out the member's cancel radio; these forged POSTs
    # prove the form enforces the same invariant server-side.

    @pytest.mark.usefixtures("enrollment_config")
    def test_forged_cancel_for_enrolled_member_is_rejected(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=member,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "cancel"}
        )

        assert response.status_code == HTTPStatus.OK
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert f"Invalid choice for {member.name}: cancel" in texts
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.CONFIRMED

    @pytest.mark.usefixtures("enrollment_config")
    def test_forged_cancel_for_waiting_member_is_rejected(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=member,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "cancel"}
        )

        assert response.status_code == HTTPStatus.OK
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.WAITING

    @pytest.mark.usefixtures("enrollment_config")
    def test_forged_waitlist_for_enrolled_member_is_rejected(
        self, authenticated_client, active_user, agenda_item
    ):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=member,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "waitlist"}
        )

        assert response.status_code == HTTPStatus.OK
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.CONFIRMED


class TestMemberAllowanceOnRestrictedEvent:
    @staticmethod
    def _restrict_with_leader_access(enrollment_config, leader):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=leader.email,
            allowed_slots=2,
        )

    def test_direct_member_without_slots_gets_no_choices(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        self._restrict_with_leader_access(enrollment_config, active_user)
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert "Mira Member" in content
        assert f'id="user_{member.pk}_enroll"' not in content
        assert f'id="user_{member.pk}_waitlist"' not in content
        assert "Access required" in content

    def test_consenting_member_without_slots_gets_no_hold_choice(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        self._restrict_with_leader_access(enrollment_config, active_user)
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
        )
        content = response.content.decode()
        assert response.status_code == HTTPStatus.OK
        assert f'id="user_{member.pk}_enroll"' not in content
        assert "Access required" in content

    def test_post_enroll_for_member_without_slots_is_rejected(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        self._restrict_with_leader_access(enrollment_config, active_user)
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )

        assert response.status_code == HTTPStatus.OK
        assert not SessionParticipation.objects.filter(user=member).exists()

    def test_member_with_own_slots_can_be_enrolled(
        self, authenticated_client, active_user, agenda_item, enrollment_config
    ):
        self._restrict_with_leader_access(enrollment_config, active_user)
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_BY_DEFAULT
        )
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=member.email,
            allowed_slots=1,
        )
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.CONFIRMED


class TestWayOutOfHeldSeat:
    def _held_seat(self, authenticated_client, active_user, agenda_item):
        _, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)
        authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "enroll"}
        )
        return member, SessionParticipation.objects.get(user=member)

    @pytest.mark.usefixtures("enrollment_config")
    def test_member_declines_held_seat_from_claim_page(
        self, authenticated_client, client, active_user, agenda_item
    ):
        member, participation = self._held_seat(
            authenticated_client, active_user, agenda_item
        )

        response = client.post(
            reverse(
                "web:chronology:offer-decline",
                kwargs={"token": participation.claim_token},
            )
        )

        assert response.status_code == HTTPStatus.FOUND
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert "Offer declined — the seat was released." in texts
        assert not SessionParticipation.objects.filter(user=member).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_leader_sees_held_seat_with_withdraw_option(
        self, authenticated_client, active_user, agenda_item
    ):
        member, _ = self._held_seat(authenticated_client, active_user, agenda_item)

        response = authenticated_client.get(_url(agenda_item))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/enroll_select.html",
            context_data=ANY,
            # The hold's own flash from the setup POST is rendered on this GET.
            messages=[
                (
                    messages.SUCCESS,
                    f"Seat held (awaiting their approval): {member.name}",
                )
            ],
        )
        content = " ".join(response.content.decode().split())
        assert "Seat held — awaiting their approval" in content
        # The held seat starts checked and stays toggleable, so unchecking it
        # withdraws the seat.
        tag = input_tag(content, member.pk)
        assert "checked" in tag
        assert "disabled" not in tag

    @pytest.mark.usefixtures("enrollment_config")
    def test_leader_withdraws_held_seat(
        self, authenticated_client, active_user, agenda_item
    ):
        member, _ = self._held_seat(authenticated_client, active_user, agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "cancel"}
        )

        assert response.status_code == HTTPStatus.FOUND
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        assert f"Cancelled: {member.name}" in texts
        assert not SessionParticipation.objects.filter(user=member).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_withdrawn_seat_rolls_on_to_the_waitlist(
        self, authenticated_client, active_user, agenda_item
    ):
        member, _ = self._held_seat(authenticated_client, active_user, agenda_item)
        session = agenda_item.session
        session.participants_limit = 1
        session.save()
        waiter = UserFactory(username="waiter2", email="waiter2@example.com")
        waiting = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        authenticated_client.post(
            _url(agenda_item), data={f"user_{member.pk}": "cancel"}
        )

        waiting.refresh_from_db()
        assert waiting.status == SessionParticipationStatus.CONFIRMED
        assert not SessionParticipation.objects.filter(user=member).exists()


class TestHeldSeatViaDesiredState:
    @pytest.mark.usefixtures("enrollment_config")
    def test_desired_include_of_inviting_member_is_skipped_when_full(
        self, authenticated_client, active_user, agenda_item
    ):
        # A held seat must occupy a confirmed spot — there is no waitlisted form
        # of it — so on a full session the member's include is skipped rather
        # than turned into an error or a phantom offer.
        _led_party_with_member(active_user, consent=PartyConsentMode.ACCEPT_INVITES)
        _reassign_presenter(agenda_item)
        session = agenda_item.session
        session.participants_limit = 1
        session.save(update_fields=["participants_limit"])
        SessionParticipation.objects.create(
            user=UserFactory(username="taken", email="taken@example.com"),
            session=session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        member = PartyMembership.objects.exclude(member=active_user).get().member

        response = authenticated_client.post(
            _url(agenda_item),
            data={"enroll_mode": "desired", f"user_{member.pk}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[(messages.WARNING, "No changes.")],
        )
        assert not SessionParticipation.objects.filter(user=member).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_desired_include_holds_a_seat_when_there_is_room(
        self, authenticated_client, active_user, agenda_item
    ):
        # The checkbox flow reaches the same held-seat outcome as the explicit
        # legacy post: an included ACCEPT_INVITES member gets an OFFERED spot.
        party, member = _led_party_with_member(
            active_user, consent=PartyConsentMode.ACCEPT_INVITES
        )
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"enroll_mode": "desired", f"user_{member.pk}": "include"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[
                (
                    messages.SUCCESS,
                    f"Seat held (awaiting their approval): {member.name}",
                )
            ],
        )
        participation = SessionParticipation.objects.get(user=member)
        assert participation.status == SessionParticipationStatus.OFFERED
        assert participation.party_id == party.pk
