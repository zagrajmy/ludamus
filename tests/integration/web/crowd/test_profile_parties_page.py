from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    MAX_CONNECTED_USERS,
    Notification,
    Party,
    PartyMembership,
    User,
)
from ludamus.pacts.crowd import UserType
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import (
    PartyConsentMode,
    PartyDTO,
    PartyInviteDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
)
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response

URL = reverse("web:crowd:profile-parties")


def _member_dto(user, party, **overrides):
    membership = PartyMembership.objects.get(party=party, member=user)
    values = {
        "membership_pk": membership.pk,
        "user_pk": user.pk,
        "name": user.get_full_name(),
        "slug": user.slug,
        "is_login_less": user.user_type == UserType.CONNECTED,
        "is_leader": party.leader_id == user.pk,
        "consent_mode": PartyConsentMode(membership.consent_mode),
        "status": PartyMembershipStatus(membership.status),
        "claim_token": user.claim_token,
    }
    values.update(overrides)
    return PartyMemberDTO(**values)


def _party_dto(party, viewer, members):
    return PartyDTO(
        pk=party.pk,
        name=party.name,
        leader_pk=party.leader_id,
        leader_name=party.leader.get_full_name(),
        is_leader=party.leader_id == viewer.pk,
        members=members,
    )


def _base_context(**overrides):
    context = {
        "parties": [],
        "invites": [],
        "companions_count": 0,
        "max_connected_users": MAX_CONNECTED_USERS,
        "can_add_companion": True,
        "create_companion_form": ANY,
        "invite_form": ANY,
        "party_form": ANY,
    }
    context.update(overrides)
    return context


class TestPartiesPageView:
    def test_get_empty(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(),
            template_name="crowd/user/parties.html",
            contains="No party yet",
        )

    def test_get_default_party_with_companion(
        self, authenticated_client, active_user, connected_user
    ):
        party = Party.objects.get(leader=active_user)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(
                parties=[
                    {
                        "party": _party_dto(
                            party,
                            active_user,
                            [
                                _member_dto(active_user, party),
                                _member_dto(connected_user, party),
                            ],
                        ),
                        "members": [
                            {"member": _member_dto(active_user, party), "form": None},
                            {"member": _member_dto(connected_user, party), "form": ANY},
                        ],
                        "is_default": True,
                    }
                ],
                companions_count=1,
            ),
            template_name="crowd/user/parties.html",
        )

    def test_get_shows_membership_in_someone_elses_party(
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

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(
                parties=[
                    {
                        "party": _party_dto(
                            party,
                            active_user,
                            [
                                _member_dto(friend, party),
                                _member_dto(active_user, party),
                            ],
                        ),
                        "members": [
                            {"member": _member_dto(friend, party), "form": None},
                            {"member": _member_dto(active_user, party), "form": None},
                        ],
                        "is_default": False,
                    }
                ]
            ),
            template_name="crowd/user/parties.html",
            contains=["Ekipa", "Leave party"],
        )

    def test_get_lists_pending_invites(self, authenticated_client, active_user):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        invite = PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(
                invites=[
                    PartyInviteDTO(
                        membership_pk=invite.pk,
                        party_pk=party.pk,
                        party_name="Ekipa",
                        leader_name="Frida Friend",
                    )
                ]
            ),
            template_name="crowd/user/parties.html",
            contains=["Join party", "Decline"],
        )


class TestPartyCreateActionView:
    def test_post_creates_party_with_leader_membership(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.post(
            reverse("web:crowd:parties-create"), data={"name": "Wtorkowa ekipa"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Party created.")],
        )
        party = Party.objects.get(name="Wtorkowa ekipa")
        assert party.leader_id == active_user.pk
        membership = party.memberships.get()
        assert membership.member_id == active_user.pk
        assert membership.status == PartyMembershipStatus.ACTIVE

    def test_post_requires_name(self, authenticated_client):
        response = authenticated_client.post(reverse("web:crowd:parties-create"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.ERROR, "Give the party a name.")],
        )
        assert not Party.objects.exists()


class TestPartyRenameActionView:
    def test_post_renames_led_party(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="")

        response = authenticated_client.post(
            reverse("web:crowd:parties-rename", kwargs={"pk": party.pk}),
            data={"name": "Rodzina"},
        )

        party.refresh_from_db()
        assert party.name == "Rodzina"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Party renamed.")],
        )

    def test_post_rejects_foreign_party(self, authenticated_client):
        stranger = UserFactory(username="stranger")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.post(
            reverse("web:crowd:parties-rename", kwargs={"pk": party.pk}),
            data={"name": "Mine now"},
        )

        party.refresh_from_db()
        assert party.name == "Theirs"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.ERROR, "Could not rename this party.")],
        )


class TestPartyDeleteActionView:
    def test_post_deletes_empty_led_party(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Old crew")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-delete", kwargs={"pk": party.pk})
        )

        assert not Party.objects.filter(pk=party.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Party deleted.")],
        )

    def test_post_refuses_party_with_companions(
        self, authenticated_client, active_user, connected_user
    ):
        party = Party.objects.get(leader=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:parties-delete", kwargs={"pk": party.pk})
        )

        assert Party.objects.filter(pk=party.pk).exists()
        assert User.objects.filter(pk=connected_user.pk).exists()
        expected = (
            "This party still has companions. Remove them first — "
            "their profiles would be left without a caretaker."
        )
        assert_response(
            response, HTTPStatus.FOUND, url=URL, messages=[(messages.ERROR, expected)]
        )


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
            self._url(party), data={"email": "frida@example.com"}
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
            url=URL,
            messages=[(messages.SUCCESS, "Invitation sent.")],
        )

    def test_post_unknown_email(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(
            self._url(party), data={"email": "nobody@example.com"}
        )

        expected = (
            "No account uses this email. Ask them to sign up first, "
            "or add them as a companion you enroll yourself."
        )
        assert_response(
            response, HTTPStatus.FOUND, url=URL, messages=[(messages.ERROR, expected)]
        )

    def test_post_already_member(self, authenticated_client, active_user):
        friend = UserFactory(
            username="friend", name="Frida Friend", email="frida@example.com"
        )
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)
        PartyMembership.objects.create(party=party, member=friend)

        response = authenticated_client.post(
            self._url(party), data={"email": "frida@example.com"}
        )

        assert PartyMembership.objects.filter(party=party, member=friend).count() == 1
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.INFO, "This person is already in the party.")],
        )

    def test_post_rejects_foreign_party(self, authenticated_client):
        stranger = UserFactory(username="stranger", email="s@example.com")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.post(
            self._url(party), data={"email": "s@example.com"}
        )

        assert not PartyMembership.objects.filter(party=party).exists()
        expected = (
            "No account uses this email. Ask them to sign up first, "
            "or add them as a companion you enroll yourself."
        )
        assert_response(
            response, HTTPStatus.FOUND, url=URL, messages=[(messages.ERROR, expected)]
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
            url=URL,
            messages=[(messages.SUCCESS, "Member removed.")],
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
            url=URL,
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
    def test_companion_lands_in_default_party(self, authenticated_client, active_user):
        sponsor_user(leader=active_user, member=active_user)

        response = authenticated_client.post(
            reverse("web:crowd:profile-connected-users"),
            data={"name": "Kiddo", "user_type": UserType.CONNECTED},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
        )
        companion = User.objects.get(name="Kiddo")
        membership = PartyMembership.objects.get(member=companion)
        assert membership.party.leader_id == active_user.pk
        assert membership.consent_mode == PartyConsentMode.ACCEPT_BY_DEFAULT
