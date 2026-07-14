from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Notification, Party, PartyMembership
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import (
    InvitablePartyDTO,
    PartyConsentMode,
    PartyMembershipStatus,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.crowd.test_profile_parties_page import URL, _detail_url


class TestPartyInviteActionView:
    def _url(self, party):
        return reverse("web:crowd:parties-invite", kwargs={"pk": party.pk})

    def test_post_invites_existing_user(self, authenticated_client, active_user):
        friend = UserFactory(
            username="friend", name="Frida Friend", email="frida@example.com"
        )
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"identifier": "frida@example.com"}
        )

        membership = PartyMembership.objects.get(party=party, member=friend)
        assert membership.status == PartyMembershipStatus.INVITED
        assert membership.consent_mode == PartyConsentMode.ACCEPT_INVITES
        notification = Notification.objects.get(recipient=friend)
        assert notification.kind == NotificationKind.PARTY_INVITE
        assert "Ekipa" in notification.title
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Invitation sent.")],
        )

    def test_post_unknown_email(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"identifier": "nobody@example.com"}
        )

        expected = (
            "No account matches that email or Discord username. Ask them "
            "to sign up first, share your invite link, or add them as a "
            "companion you enroll yourself."
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, expected)],
        )

    def test_post_invites_by_discord_username(self, authenticated_client, active_user):
        friend = UserFactory(
            username="friend", name="Frida Friend", discord_username="frida#42"
        )
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"identifier": "frida#42"}
        )

        membership = PartyMembership.objects.get(party=party, member=friend)
        assert membership.status == PartyMembershipStatus.INVITED
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Invitation sent.")],
        )

    def test_post_ambiguous_discord_username(self, authenticated_client, active_user):
        UserFactory(username="one", discord_username="dup")
        UserFactory(username="two", discord_username="dup")
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"identifier": "dup"}
        )

        assert PartyMembership.objects.filter(party=party).count() == 1
        expected = (
            "More than one account uses that Discord username. "
            "Invite them by email instead."
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, expected)],
        )

    def test_post_already_member(self, authenticated_client, active_user):
        friend = UserFactory(
            username="friend", name="Frida Friend", email="frida@example.com"
        )
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)
        PartyMembership.objects.create(party=party, member=friend)

        response = authenticated_client.post(
            self._url(party), data={"identifier": "frida@example.com"}
        )

        assert PartyMembership.objects.filter(party=party, member=friend).count() == 1
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.INFO, "This person is already in the party.")],
        )

    def test_post_rejects_foreign_party(self, authenticated_client):
        stranger = UserFactory(username="stranger", email="s@example.com")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.post(
            self._url(party), data={"identifier": "s@example.com"}
        )

        assert not PartyMembership.objects.filter(party=party).exists()
        expected = (
            "No account matches that email or Discord username. Ask them "
            "to sign up first, share your invite link, or add them as a "
            "companion you enroll yourself."
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, expected)],
        )


class TestPartyCompanionAddActionView:
    def _url(self, party):
        return reverse("web:crowd:parties-add-companion", kwargs={"pk": party.pk})

    def test_post_adds_owned_companion_by_display_name(
        self, authenticated_client, active_user, companion
    ):
        companion.name = "Kiddo"
        companion.save(update_fields=["name"])
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"display_name": " kiddo "}
        )

        membership = PartyMembership.objects.get(party=party, member=companion)
        assert membership.status == PartyMembershipStatus.ACTIVE
        assert membership.consent_mode == PartyConsentMode.ACCEPT_BY_DEFAULT
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Companion added to the party.")],
        )

    def test_post_unknown_name(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"display_name": "Nobody"}
        )

        assert PartyMembership.objects.filter(party=party).count() == 1
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party) + "?add-companion=1",
            messages=[(messages.ERROR, "No companion matches that display name.")],
        )

    def test_post_already_member(self, authenticated_client, active_user, companion):
        companion.name = "Kiddo"
        companion.save(update_fields=["name"])
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)
        PartyMembership.objects.create(party=party, member=companion)

        response = authenticated_client.post(
            self._url(party), data={"display_name": "Kiddo"}
        )

        assert (
            PartyMembership.objects.filter(party=party, member=companion).count() == 1
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.INFO, "This companion is already in the party.")],
        )

    def test_post_rejects_foreign_party(self, authenticated_client, companion):
        companion.name = "Kiddo"
        companion.manager = UserFactory(username="stranger")
        companion.save(update_fields=["name", "manager"])
        party = Party.objects.create(
            leader=UserFactory(username="leader"), name="Theirs"
        )

        response = authenticated_client.post(
            self._url(party), data={"display_name": "Kiddo"}
        )

        assert not PartyMembership.objects.filter(party=party).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party) + "?add-companion=1",
            messages=[(messages.ERROR, "No companion matches that display name.")],
        )


class TestPartyInviteLinkActionView:
    def _url(self, party):
        return reverse("web:crowd:parties-invite-link", kwargs={"pk": party.pk})

    def test_regenerates_link(self, authenticated_client, active_user):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", invite_token="old-token"
        )
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(self._url(party))

        party.refresh_from_db()
        assert party.invite_token
        assert party.invite_token != "old-token"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Invite link regenerated.")],
        )

    def test_rejects_non_leader(self, authenticated_client):
        stranger = UserFactory(username="stranger")
        party = Party.objects.create(
            leader=stranger, name="Theirs", invite_token="theirs"
        )

        response = authenticated_client.post(self._url(party))

        party.refresh_from_db()
        assert party.invite_token == "theirs"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not regenerate the invite link.")],
        )


class TestPartyJoinPageView:
    def _url(self, token):
        return reverse("web:crowd:parties-join", kwargs={"token": token})

    def test_get_shows_join_page(self, authenticated_client):
        leader = UserFactory(username="leader", name="Lena Leader")
        party = Party.objects.create(
            leader=leader, name="Ekipa", invite_token="tok-123"
        )
        PartyMembership.objects.create(party=party, member=leader)

        response = authenticated_client.get(self._url("tok-123"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "party": InvitablePartyDTO(
                    pk=party.pk,
                    name="Ekipa",
                    leader_name="Lena Leader",
                    already_member=False,
                ),
                "token": "tok-123",
            },
            template_name="crowd/user/party_join.html",
            contains=["Ekipa", "Join party"],
        )

    def test_get_invalid_token(self, authenticated_client):
        response = authenticated_client.get(self._url("nope"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:crowd:profile-parties"),
            messages=[(messages.ERROR, "This invite link is invalid.")],
        )

    def test_get_already_member_redirects(self, authenticated_client, active_user):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", invite_token="tok-9"
        )
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.get(self._url("tok-9"))

        assert_response(response, HTTPStatus.FOUND, url=_detail_url(party))

    def test_post_joins(self, authenticated_client, active_user):
        leader = UserFactory(username="leader", name="Lena Leader")
        party = Party.objects.create(
            leader=leader, name="Ekipa", invite_token="join-me"
        )
        PartyMembership.objects.create(party=party, member=leader)

        response = authenticated_client.post(self._url("join-me"))

        membership = PartyMembership.objects.get(party=party, member=active_user)
        assert membership.status == PartyMembershipStatus.ACTIVE
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "You joined the party.")],
        )

    def test_post_already_member(self, authenticated_client, active_user):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", invite_token="mine"
        )
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(self._url("mine"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.INFO, "You're already in this party.")],
        )


class TestPartyInviteResponseActionViews:
    def _invite(self, active_user):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        return PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

    def test_accept(self, authenticated_client, active_user):
        invite = self._invite(active_user)

        response = authenticated_client.post(
            reverse("web:crowd:party-invites-accept", kwargs={"pk": invite.pk})
        )

        invite.refresh_from_db()
        assert invite.status == PartyMembershipStatus.ACTIVE
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "You joined the party.")],
        )

    def test_decline(self, authenticated_client, active_user):
        invite = self._invite(active_user)

        response = authenticated_client.post(
            reverse("web:crowd:party-invites-decline", kwargs={"pk": invite.pk})
        )

        assert not PartyMembership.objects.filter(pk=invite.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Invitation declined.")],
        )

    def test_accept_rejects_someone_elses_invite(self, authenticated_client):
        other = UserFactory(username="other")
        invite = self._invite(other)

        response = authenticated_client.post(
            reverse("web:crowd:party-invites-accept", kwargs={"pk": invite.pk})
        )

        invite.refresh_from_db()
        assert invite.status == PartyMembershipStatus.INVITED
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.ERROR, "This invitation is no longer valid.")],
        )
