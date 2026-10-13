from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import SphereInvitation, SphereMembership
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import InvitationPreviewDTO, SphereInvitationDTO, TeamMemberDTO
from tests.integration.conftest import SphereFactory, UserFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.multiverse.helpers import (
    READ_ONLY_ROLE_ERROR,
    assert_not_a_sphere_manager,
    sphere_sidebar_context,
)

# secrets.token_urlsafe(32): 32 random bytes, base64-encoded without padding.
URLSAFE_32_BYTES_LENGTH = 43
TEAM_URL = reverse("multiverse:panel:team")
INVITE_URL = reverse("multiverse:panel:team-invite")
INVALID_LINK = (
    "This invitation link is no longer valid. Ask the person who sent it for "
    "a new one."
)


def _invitation(sphere, *, role=SphereRole.MANAGER, token="tok", **fields):
    return SphereInvitation.objects.create(
        sphere=sphere,
        role=role,
        token=token,
        expires_at=fields.pop("expires_at", datetime.now(UTC) + timedelta(days=7)),
        **fields,
    )


def _join_url(token):
    return reverse("multiverse:join", kwargs={"token": token})


@pytest.fixture(name="manager")
def manager_fixture(active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.MANAGER
    )
    return active_user


@pytest.fixture(name="comms")
def comms_fixture(active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )
    return active_user


class TestTeamPageView:
    def test_redirects_anonymous_user_to_login(self, client):
        response = client.get(TEAM_URL)

        assert_login_required(response, TEAM_URL)

    def test_refuses_a_stranger(self, authenticated_client):
        response = authenticated_client.get(TEAM_URL)

        assert_not_a_sphere_manager(response)

    def test_manager_sees_members_invitations_and_the_form(
        self, authenticated_client, manager, sphere
    ):
        invitation = _invitation(sphere, role=SphereRole.COMMS, created_by=manager)
        _invitation(
            sphere, token="used", accepted_at=datetime.now(UTC), accepted_by=manager
        )
        _invitation(
            sphere, token="old", expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
        _invitation(SphereFactory(), token="elsewhere")

        response = authenticated_client.get(TEAM_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/team.html",
            context_data={
                **sphere_sidebar_context(active_nav="team"),
                "members": [
                    TeamMemberDTO(
                        user_id=manager.pk,
                        name="Test User",
                        email="testuser@example.com",
                        role=SphereRole.MANAGER,
                    )
                ],
                "invitations": [
                    SphereInvitationDTO(
                        pk=invitation.pk,
                        role=SphereRole.COMMS,
                        token="tok",
                        invited_by="Test User",
                        creation_time=invitation.creation_time,
                        expires_at=invitation.expires_at,
                    )
                ],
                "invitation_form": ANY,
            },
        )

    def test_comms_member_reads_the_team_but_gets_no_invite_controls(
        self, authenticated_client, comms, sphere
    ):
        _invitation(sphere)

        response = authenticated_client.get(TEAM_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/team.html",
            context_data={
                **sphere_sidebar_context(active_nav="team"),
                "members": [
                    TeamMemberDTO(
                        user_id=comms.pk,
                        name="Test User",
                        email="testuser@example.com",
                        role=SphereRole.COMMS,
                    )
                ],
                "invitations": [],
                "invitation_form": None,
            },
        )


class TestTeamInviteActionView:
    def test_manager_creates_a_week_long_link_for_the_role(
        self, authenticated_client, manager, sphere
    ):
        response = authenticated_client.post(INVITE_URL, data={"role": "comms"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (
                    messages.SUCCESS,
                    "Invitation link created. Copy it and send it to the person.",
                )
            ],
        )
        invitation = SphereInvitation.objects.get(sphere=sphere)
        assert invitation.role == SphereRole.COMMS
        assert invitation.created_by == manager
        assert len(invitation.token) == URLSAFE_32_BYTES_LENGTH
        lifetime = invitation.expires_at - invitation.creation_time
        assert timedelta(days=7) - timedelta(minutes=1) < lifetime <= timedelta(days=7)

    def test_rejects_an_unknown_role(self, authenticated_client, manager):
        response = authenticated_client.post(INVITE_URL, data={"role": "owner"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[(messages.ERROR, "Pick a role for the invitation.")],
        )
        assert not SphereInvitation.objects.exists()

    def test_comms_member_cannot_invite(self, authenticated_client, comms):
        response = authenticated_client.post(INVITE_URL, data={"role": "manager"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert not SphereInvitation.objects.exists()


class TestTeamInviteRevokeActionView:
    @staticmethod
    def _url(invitation):
        return reverse(
            "multiverse:panel:team-invite-revoke", kwargs={"pk": invitation.pk}
        )

    def test_manager_revokes_an_open_invitation(
        self, authenticated_client, manager, sphere
    ):
        invitation = _invitation(sphere)

        response = authenticated_client.post(self._url(invitation))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[(messages.SUCCESS, "Invitation revoked.")],
        )
        assert not SphereInvitation.objects.exists()

    def test_another_spheres_invitation_is_left_alone(
        self, authenticated_client, manager
    ):
        foreign = _invitation(SphereFactory())

        response = authenticated_client.post(self._url(foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (messages.ERROR, "That invitation was already used or has expired.")
            ],
        )
        assert SphereInvitation.objects.filter(pk=foreign.pk).exists()

    def test_an_accepted_invitation_keeps_its_record(
        self, authenticated_client, manager, sphere
    ):
        accepted = _invitation(
            sphere, accepted_at=datetime.now(UTC), accepted_by=manager
        )

        authenticated_client.post(self._url(accepted))

        assert SphereInvitation.objects.filter(pk=accepted.pk).exists()


class TestJoinSpherePageView:
    def test_redirects_anonymous_user_to_login(self, client, sphere):
        _invitation(sphere)

        response = client.get(_join_url("tok"))

        assert_login_required(response, _join_url("tok"))

    def test_shows_what_the_link_grants(self, authenticated_client, sphere):
        _invitation(
            sphere,
            role=SphereRole.COMMS,
            created_by=UserFactory(name="Ola Organizatorka"),
        )

        response = authenticated_client.get(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/join.html",
            context_data={
                "invitation": InvitationPreviewDTO(
                    sphere_name=sphere.name,
                    role=SphereRole.COMMS,
                    invited_by="Ola Organizatorka",
                )
            },
        )

    def test_accepting_adds_the_role_and_spends_the_link(
        self, authenticated_client, active_user, sphere
    ):
        invitation = _invitation(sphere, role=SphereRole.COMMS)

        response = authenticated_client.post(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[(messages.SUCCESS, "You joined the sphere's team.")],
        )
        membership = SphereMembership.objects.get(sphere=sphere, user=active_user)
        assert membership.role == SphereRole.COMMS
        invitation.refresh_from_db()
        assert invitation.accepted_by == active_user
        assert invitation.accepted_at is not None

    @pytest.mark.parametrize(
        "fields",
        (
            {"expires_at": datetime.now(UTC) - timedelta(minutes=1)},
            {"accepted_at": datetime.now(UTC)},
        ),
        ids=("expired", "used"),
    )
    def test_a_spent_link_grants_nothing(
        self, authenticated_client, active_user, sphere, fields
    ):
        _invitation(sphere, **fields)

        response = authenticated_client.post(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.ERROR, INVALID_LINK)],
        )
        assert not SphereMembership.objects.filter(user=active_user).exists()

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_another_spheres_link_grants_nothing_here(
        self, authenticated_client, active_user, method
    ):
        _invitation(SphereFactory())

        response = getattr(authenticated_client, method)(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.ERROR, INVALID_LINK)],
        )
        assert not SphereMembership.objects.filter(user=active_user).exists()
        assert SphereInvitation.objects.get().accepted_at is None

    def test_a_member_leaves_the_link_unspent(
        self, authenticated_client, comms, sphere
    ):
        invitation = _invitation(sphere, role=SphereRole.MANAGER)

        response = authenticated_client.post(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (
                    messages.INFO,
                    (
                        "You're already on this sphere's team, so the link is "
                        "still unused."
                    ),
                )
            ],
        )
        assert SphereMembership.objects.get(user=comms).role == SphereRole.COMMS
        invitation.refresh_from_db()
        assert invitation.accepted_at is None

    def test_a_private_sphere_lets_the_invitee_in(
        self, authenticated_client, active_user, sphere
    ):
        sphere.visibility = "private"
        sphere.save(update_fields=["visibility"])
        _invitation(sphere)

        response = authenticated_client.post(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[(messages.SUCCESS, "You joined the sphere's team.")],
        )
        assert SphereMembership.objects.filter(sphere=sphere, user=active_user).exists()
