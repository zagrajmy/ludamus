from http import HTTPStatus

from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory


def _url(party):
    return reverse("web:crowd:party-detail", kwargs={"pk": party.pk})


class TestPartyDetailPageView:
    def test_get_led_party_shows_members_and_forms(
        self, authenticated_client, active_user, connected_user
    ):
        party = Party.objects.get(leader=active_user)

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.OK
        assert response.context["party"].pk == party.pk
        assert response.context["party"].is_leader
        assert response.context["rename_form"] is not None
        assert response.context["invite_form"] is not None
        assert response.context["history"] == []
        content = response.content.decode()
        assert connected_user.get_full_name() in content
        assert "Invite a member" in content
        assert "Delete party" in content

    def test_get_membership_shows_leave_and_consent(
        self, authenticated_client, active_user
    ):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.ACTIVE,
        )

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.OK
        assert not response.context["party"].is_leader
        assert response.context["rename_form"] is None
        assert response.context["invite_form"] is None
        content = response.content.decode()
        assert "Leave party" in content
        assert "Allow direct enrollment" in content

    def test_get_foreign_party_is_not_found(self, authenticated_client):
        stranger = UserFactory(username="stranger")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_pending_invite_is_not_found(self, authenticated_client, active_user):
        friend = UserFactory(username="friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_requires_login(self, client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")

        response = client.get(_url(party))

        assert response.status_code == HTTPStatus.FOUND


class TestPartyDetailSessionHistory:
    def _enroll_party(self, party, session, *users):
        for user in users:
            SessionParticipation.objects.create(
                session=session,
                user=user,
                party=party,
                status=SessionParticipationStatus.CONFIRMED,
            )

    def test_history_groups_party_sessions_by_event(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        party = Party.objects.get(leader=active_user)
        session.title = "Wspólna Wyprawa"
        session.save()
        self._enroll_party(party, session, active_user, connected_user)

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.OK
        (group,) = response.context["history"]
        assert group["event_name"] == session.event.name
        assert group["event_slug"] == session.event.slug
        (card,) = group["cards"]
        assert card.session.pk == session.pk
        assert card.user_enrolled
        assert card.agenda_item.start_time == agenda_item.start_time
        content = response.content.decode()
        assert "Wspólna Wyprawa" in content
        assert session.event.name in content

    def test_history_skips_solo_enrollments(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        _ = connected_user, agenda_item
        party = Party.objects.get(leader=active_user)
        SessionParticipation.objects.create(
            session=session,
            user=active_user,
            party=None,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.OK
        assert response.context["history"] == []
        assert "No sessions together yet" in response.content.decode()

    def test_history_card_is_pretend_full_when_presenter_shadowbanned_viewer(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        _ = agenda_item
        party = Party.objects.get(leader=active_user)
        self._enroll_party(party, session, active_user, connected_user)
        banner = UserFactory(username="gm", name="GM", email="gm@example.com")
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.get(_url(party))

        assert response.status_code == HTTPStatus.OK
        (group,) = response.context["history"]
        (card,) = group["cards"]
        assert card.pretend_full
        assert card.is_full
        assert all(p.user.pk < 0 for p in card.session_participations)
