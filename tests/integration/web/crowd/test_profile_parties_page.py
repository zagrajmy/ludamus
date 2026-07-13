from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from ludamus.links.db.django.models import (
    MAX_COMPANIONS,
    Party,
    PartyMembership,
    User,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import CompanionDTO, UserType
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


def _avatar_url(user):
    if user.use_gravatar:
        return gravatar_url(user.email) or ""
    return user.avatar_url or gravatar_url(user.email) or ""


def _member_dto(user, party, *, viewer=None, **overrides):
    membership = PartyMembership.objects.get(party=party, member=user)
    viewer_pk = viewer.pk if viewer is not None else party.leader_id
    is_managed_by_viewer = user.manager_id == viewer_pk
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
        "claim_token": user.claim_token if is_managed_by_viewer else "",
        "avatar_url": _avatar_url(user),
        "is_managed_by_viewer": is_managed_by_viewer,
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
        is_active_member=any(
            member.user_pk == viewer.pk
            and member.status == PartyMembershipStatus.ACTIVE
            for member in members
        ),
        created_at=party.created_at,
        members=members,
    )


def _entry(party, viewer, members):
    active = [m for m in members if m.status == PartyMembershipStatus.ACTIVE]
    return {
        "party": _party_dto(party, viewer, members),
        "stack": active[:5],
        "stack_overflow": max(0, len(active) - 5),
        "active_count": len(active),
    }


def _detail_url(party):
    return reverse("web:crowd:party-detail", kwargs={"pk": party.pk})


def _companion_row(user):
    return {
        "companion": CompanionDTO.model_validate(user),
        "form": ANY,
        "editing": False,
    }


def _base_context(**overrides):
    context = {
        "parties": [],
        "invites": [],
        "companions": [],
        "companions_count": 0,
        "max_companions": MAX_COMPANIONS,
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
        self, authenticated_client, active_user, companion
    ):
        party = sponsor_user(leader=active_user, member=active_user)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_base_context(
                parties=[_entry(party, active_user, [_member_dto(active_user, party)])],
                companions=[_companion_row(companion)],
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

    def test_membership_query_count_is_constant_across_parties(
        self, authenticated_client, active_user
    ):
        first = Party.objects.create(leader=active_user, name="First")
        PartyMembership.objects.create(party=first, member=active_user)
        authenticated_client.get(URL)

        with CaptureQueriesContext(connection) as one_party_queries:
            one_party_response = authenticated_client.get(URL)

        second = Party.objects.create(leader=active_user, name="Second")
        PartyMembership.objects.create(party=second, member=active_user)
        with CaptureQueriesContext(connection) as two_party_queries:
            two_party_response = authenticated_client.get(URL)

        assert_response(
            one_party_response,
            HTTPStatus.OK,
            context_data=one_party_response.context_data,
            template_name="crowd/user/parties.html",
        )
        assert_response(
            two_party_response,
            HTTPStatus.OK,
            context_data=two_party_response.context_data,
            template_name="crowd/user/parties.html",
        )
        assert len(two_party_queries) == len(one_party_queries)


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

    def test_post_deletes_party_with_companions_but_preserves_identity(
        self, authenticated_client, active_user, companion
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)

        response = authenticated_client.post(
            reverse("web:crowd:parties-delete", kwargs={"pk": party.pk})
        )

        assert not Party.objects.filter(pk=party.pk).exists()
        companion.refresh_from_db()
        assert companion.manager_id == active_user.pk
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=URL,
            messages=[(messages.SUCCESS, "Party deleted.")],
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
