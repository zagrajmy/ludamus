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
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import ConnectedUserDTO, UserType
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import (
    InvitablePartyDTO,
    PartyConsentMode,
    PartyDTO,
    PartyInviteDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
)
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response

URL = reverse("web:crowd:profile-parties")


def _avatar_url(user):
    if user.use_gravatar:
        return gravatar_url(user.email) or ""
    return user.avatar_url or gravatar_url(user.email) or ""


def _member_dto(user, party, **overrides):
    membership = PartyMembership.objects.get(party=party, member=user)
    values = {
        "membership_pk": membership.pk,
        "user_pk": user.pk,
        "name": user.name,
        "full_name": user.get_full_name(),
        "username": user.username,
        "slug": user.slug,
        "is_login_less": user.user_type == UserType.CONNECTED,
        "is_leader": party.leader_id == user.pk,
        "consent_mode": PartyConsentMode(membership.consent_mode),
        "status": PartyMembershipStatus(membership.status),
        "claim_token": user.claim_token,
        "avatar_url": _avatar_url(user),
    }
    values.update(overrides)
    return PartyMemberDTO(**values)


def _party_dto(party, viewer, members, *, is_default):
    return PartyDTO(
        pk=party.pk,
        name=party.name,
        leader_pk=party.leader_id,
        leader_name=party.leader.get_full_name(),
        is_leader=party.leader_id == viewer.pk,
        is_default=is_default,
        created_at=party.created_at,
        members=members,
    )


def _entry(party, viewer, members, *, is_default):
    active = [m for m in members if m.status == PartyMembershipStatus.ACTIVE]
    return {
        "party": _party_dto(party, viewer, members, is_default=is_default),
        "stack": active[:5],
        "stack_overflow": max(0, len(active) - 5),
        "active_count": len(active),
    }


def _detail_url(party):
    return reverse("web:crowd:party-detail", kwargs={"pk": party.pk})


def _companion_row(user):
    return {
        "companion": ConnectedUserDTO.model_validate(user),
        "form": ANY,
        "editing": False,
    }


def _base_context(**overrides):
    context = {
        "parties": [],
        "invites": [],
        "companions": [],
        "companions_count": 0,
        "max_connected_users": MAX_CONNECTED_USERS,
        "can_add_companion": True,
        "create_companion_form": ANY,
        "party_form": ANY,
        "profile_active_tab": "parties",
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

    def test_get_party_and_companion_are_separate(
        self, authenticated_client, active_user, connected_user
    ):
        party = sponsor_user(leader=active_user, member=active_user)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(
                parties=[
                    _entry(
                        party,
                        active_user,
                        [_member_dto(active_user, party)],
                        is_default=True,
                    )
                ],
                companions=[_companion_row(connected_user)],
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
                    _entry(
                        party,
                        active_user,
                        [_member_dto(friend, party), _member_dto(active_user, party)],
                        is_default=False,
                    )
                ]
            ),
            template_name="crowd/user/parties.html",
            contains=["Ekipa", "History"],
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

        party = Party.objects.get(name="Wtorkowa ekipa")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Party created.")],
        )
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
            url=_detail_url(party),
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
            url=_detail_url(party),
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
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=connected_user)

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

    def test_post_foreign_party_with_companions_reads_as_not_found(
        self, authenticated_client
    ):
        stranger = UserFactory(username="stranger")
        companion = UserFactory(
            username="their-kid", user_type=UserType.CONNECTED, manager=stranger
        )
        party = sponsor_user(leader=stranger, member=stranger)
        sponsor_user(leader=stranger, member=companion)

        response = authenticated_client.post(
            reverse("web:crowd:parties-delete", kwargs={"pk": party.pk})
        )

        assert Party.objects.filter(pk=party.pk).exists()
        assert User.objects.filter(pk=companion.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.ERROR, "Could not delete this party.")],
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


class TestPartyInviteLinkActionView:
    def _url(self, party):
        return reverse("web:crowd:parties-invite-link", kwargs={"pk": party.pk})

    def test_creates_link(self, authenticated_client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        PartyMembership.objects.create(party=party, member=active_user)

        response = authenticated_client.post(self._url(party))

        party.refresh_from_db()
        assert party.invite_token
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.SUCCESS, "Invite link ready.")],
        )

    def test_regenerates_link(self, authenticated_client, active_user):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", invite_token="old-token"
        )
        PartyMembership.objects.create(party=party, member=active_user)

        authenticated_client.post(self._url(party))

        party.refresh_from_db()
        assert party.invite_token
        assert party.invite_token != "old-token"

    def test_rejects_non_leader(self, authenticated_client):
        stranger = UserFactory(username="stranger")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.post(self._url(party))

        party.refresh_from_db()
        assert not party.invite_token
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(party),
            messages=[(messages.ERROR, "Could not create an invite link.")],
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
        self, authenticated_client, active_user, connected_user
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=connected_user)
        membership = PartyMembership.objects.get(party=party, member=connected_user)

        response = authenticated_client.post(
            reverse(
                "web:crowd:parties-member-remove",
                kwargs={"pk": party.pk, "membership_pk": membership.pk},
            )
        )

        assert PartyMembership.objects.filter(pk=membership.pk).exists()
        assert User.objects.filter(pk=connected_user.pk).exists()
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

        assert response.status_code == HTTPStatus.OK
        assert "Allow direct enrollment" in response.content.decode()

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
