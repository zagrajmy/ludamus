from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    MAX_CONNECTED_USERS,
    Party,
    PartyMembership,
    User,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.crowd import ConnectedUserDTO, UserType
from ludamus.pacts.party import (
    PartyConsentMode,
    PartyDTO,
    PartyMemberDTO,
    PartyMembershipStatus,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

PARTIES_URL = reverse("web:crowd:profile-parties")


def _member_dto(user, party):
    membership = PartyMembership.objects.get(party=party, member=user)
    return PartyMemberDTO(
        membership_pk=membership.pk,
        user_pk=user.pk,
        name=user.name,
        full_name=user.get_full_name(),
        username=user.username,
        slug=user.slug,
        is_login_less=user.user_type == UserType.CONNECTED,
        is_leader=party.leader_id == user.pk,
        consent_mode=PartyConsentMode(membership.consent_mode),
        status=PartyMembershipStatus(membership.status),
        claim_token=user.claim_token,
        avatar_url=user.avatar_url or gravatar_url(user.email) or "",
    )


class TestProfileConnectedUsersPageView:
    URL = reverse("web:crowd:profile-connected-users")

    def test_get_redirects_to_parties(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=PARTIES_URL)

    def test_post_ok(self, authenticated_client, active_user, faker):
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
            url=PARTIES_URL,
        )
        user = User.objects.get(name=data["name"])
        assert user.user_type == UserType.CONNECTED
        membership = PartyMembership.objects.get(member=user)
        assert membership.party.leader_id == active_user.pk

    def test_post_error_form_invalid(self, authenticated_client):
        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.WARNING, "Please correct the errors below.")],
            context_data={
                "form": ANY,
                "view": ANY,
                "parties": [],
                "invites": [],
                "companions": [],
                "companions_count": 0,
                "max_connected_users": MAX_CONNECTED_USERS,
                "can_add_companion": True,
                "create_companion_form": ANY,
                "party_form": ANY,
                "profile_active_tab": "parties",
            },
            template_name=["crowd/user/parties.html"],
        )

    def test_post_error_max_connected_users_exceeded(
        self, authenticated_client, active_user, faker
    ):
        companions = [
            UserFactory(
                username=f"user_{i}_{faker.random_int()}",
                name=f"connected_{i}_{faker.random_int()}",
                slug=f"connected-{i}-{faker.random_int()}",
                user_type=UserType.CONNECTED,
                manager=active_user,
            )
            for i in range(MAX_CONNECTED_USERS)
        ]

        data = {"name": faker.name(), "user_type": UserType.CONNECTED}
        response = authenticated_client.post(self.URL, data=data)

        party = Party.objects.get(leader=active_user)
        members = [_member_dto(user, party) for user in (active_user, *companions)]
        assert_response(
            response,
            HTTPStatus.OK,
            messages=[
                (
                    messages.ERROR,
                    f"You can only have up to {MAX_CONNECTED_USERS} connected users.",
                ),
                (messages.WARNING, "Please correct the errors below."),
            ],
            context_data={
                "form": ANY,
                "view": ANY,
                "parties": [
                    {
                        "party": PartyDTO(
                            pk=party.pk,
                            name=party.name,
                            leader_pk=active_user.pk,
                            leader_name=active_user.get_full_name(),
                            is_leader=True,
                            is_default=True,
                            created_at=party.created_at,
                            members=members,
                        ),
                        "stack": members[:5],
                        "stack_overflow": len(members) - 5,
                        "active_count": len(members),
                    }
                ],
                "invites": [],
                "companions": [
                    {
                        "companion": ConnectedUserDTO.model_validate(user),
                        "form": ANY,
                        "editing": False,
                    }
                    for user in companions
                ],
                "companions_count": MAX_CONNECTED_USERS,
                "max_connected_users": MAX_CONNECTED_USERS,
                "can_add_companion": False,
                "create_companion_form": ANY,
                "party_form": ANY,
                "profile_active_tab": "parties",
            },
            template_name=["crowd/user/parties.html"],
        )
        connected_count = User.objects.filter(user_type=UserType.CONNECTED).count()
        assert connected_count == MAX_CONNECTED_USERS

    def test_companion_join_the_leaders_existing_default_party(
        self, authenticated_client, active_user, connected_user, faker
    ):
        default_party = Party.objects.get(
            leader=active_user, memberships__member=connected_user
        )
        data = {"name": faker.name(), "user_type": UserType.CONNECTED}

        response = authenticated_client.post(self.URL, data=data)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connected user added successfully!")],
            url=PARTIES_URL,
        )
        user = User.objects.get(name=data["name"])
        assert PartyMembership.objects.get(member=user).party_id == default_party.pk
