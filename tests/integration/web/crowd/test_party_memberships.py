from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Party, PartyMembership, User
from ludamus.pacts.crowd import UserType
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response
from tests.integration.web.crowd.test_profile_parties_page import URL, _detail_url


class TestPartyMemberRemoveActionView:
    def test_post_removes_real_member(self, authenticated_client, active_user):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)
        membership = PartyMembership.objects.create(party=party, member=friend)

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert not PartyMembership.objects.filter(pk=membership.pk).exists()
        assert User.objects.filter(pk=friend.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Member removed.")],
        )

    def test_post_withdraws_pending_invitation(self, authenticated_client, active_user):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)
        membership = PartyMembership.objects.create(
            party=party,
            member=friend,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert not PartyMembership.objects.filter(pk=membership.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Invitation withdrawn.")],
        )

    def test_post_rejects_companion_membership(
        self, authenticated_client, active_user, companion
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)
        membership = PartyMembership.objects.get(party=party, member=companion)

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert PartyMembership.objects.filter(pk=membership.pk).exists()
        assert User.objects.filter(pk=companion.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not remove this member.")],
        )

    def test_post_cannot_remove_leader(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        membership = PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert PartyMembership.objects.filter(pk=membership.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not remove this member.")],
        )

    def test_non_leader_cannot_remove_another_member(
        self, authenticated_client, active_user
    ):
        leader = UserFactory(username="leader")
        other = UserFactory(username="other")
        party = Party.objects.create(leader=leader, name="Ekipa")
        PartyMembership.objects.create(party=party, member=leader)
        PartyMembership.objects.create(party=party, member=active_user)
        membership = PartyMembership.objects.create(party=party, member=other)

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert PartyMembership.objects.filter(pk=membership.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not remove this member.")],
        )


class TestPartyLeaveActionView:
    def test_post_leaves_party(self, authenticated_client, active_user):
        friend = UserFactory(username="friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-leave", kwargs={"pk": party.pk})
        )

        assert not PartyMembership.objects.filter(
            party=party, member=active_user
        ).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "You left the party.")],
        )

    def test_post_leader_cannot_leave_own_party(
        self, authenticated_client, active_user
    ):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-leave", kwargs={"pk": party.pk})
        )

        assert PartyMembership.objects.filter(party=party, member=active_user).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.ERROR, "Could not leave this party.")],
        )


class TestCompanionMembershipWriteThrough:
    def test_companion_does_not_land_in_default_party(
        self, authenticated_client, active_user
    ):
        sponsor_user(leader=active_user, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:profile-companions"),
            data={"name": "Kiddo", "user_type": UserType.CONNECTED},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Companion added successfully!")],
        )
        companion = User.objects.get(name="Kiddo")
        assert companion.manager_id == active_user.pk
        assert not PartyMembership.objects.filter(member=companion).exists()


class TestPartyConsentActionView:
    def _party_with_me_as_member(self, active_user):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        return party, PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.ACTIVE,
        )

    def test_post_grants_power_of_attorney(self, authenticated_client, active_user):
        party, membership = self._party_with_me_as_member(active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-consent", kwargs={"pk": party.pk}),
            data={"mode": "accept_by_default"},
        )

        membership.refresh_from_db()
        assert membership.consent_mode == PartyConsentMode.ACCEPT_BY_DEFAULT
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "The leader can now enroll you directly.")],
        )

    def test_post_revokes_power_of_attorney(self, authenticated_client, active_user):
        party, membership = self._party_with_me_as_member(active_user)
        membership.consent_mode = PartyConsentMode.ACCEPT_BY_DEFAULT
        membership.save()

        response = authenticated_client.post(
            reverse("web:crowd:parties-consent", kwargs={"pk": party.pk}),
            data={"mode": "accept_invites"},
        )

        membership.refresh_from_db()
        assert membership.consent_mode == PartyConsentMode.ACCEPT_INVITES
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Enrollments now wait for your approval.")],
        )

    def test_post_rejects_unknown_mode(self, authenticated_client, active_user):
        party, membership = self._party_with_me_as_member(active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-consent", kwargs={"pk": party.pk}),
            data={"mode": "whatever"},
        )

        membership.refresh_from_db()
        assert membership.consent_mode == PartyConsentMode.ACCEPT_INVITES
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not change this setting.")],
        )

    def test_leader_cannot_toggle_own_party(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Moja")
        membership = PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-consent", kwargs={"pk": party.pk}),
            data={"mode": "accept_by_default"},
        )

        membership.refresh_from_db()
        assert membership.consent_mode == PartyConsentMode.ACCEPT_INVITES
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not change this setting.")],
        )

    def test_page_renders_toggle_on_own_row(self, authenticated_client, active_user):
        party, _ = self._party_with_me_as_member(active_user)
        response = authenticated_client.get(_detail_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=response.context_data,
            template_name="crowd/user/party_detail.html",
            contains="Allow direct enrollment",
        )

    def test_own_row_shows_current_consent_state(
        self, authenticated_client, active_user
    ):
        party, membership = self._party_with_me_as_member(active_user)

        content = authenticated_client.get(_detail_url(party)).content.decode()
        assert "Asks before enrolling you" in content

        membership.consent_mode = PartyConsentMode.ACCEPT_BY_DEFAULT
        membership.save()

        content = authenticated_client.get(_detail_url(party)).content.decode()
        assert "Enrolls you directly" in content
        assert "Require my approval" in content

    def test_leader_sees_member_consent_state(self, authenticated_client, active_user):
        member = UserFactory(username="member", name="Mira Member")
        party = Party.objects.create(leader=active_user, name="Moja")
        PartyMembership.objects.create(party=party, member=active_user)
        membership = PartyMembership.objects.create(
            party=party,
            member=member,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.ACTIVE,
        )

        content = authenticated_client.get(_detail_url(party)).content.decode()
        assert "asks for approval before enrolling" in content

        membership.consent_mode = PartyConsentMode.ACCEPT_BY_DEFAULT
        membership.save()

        content = authenticated_client.get(_detail_url(party)).content.decode()
        assert "direct enrollment allowed" in content
