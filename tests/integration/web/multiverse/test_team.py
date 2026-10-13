from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import SphereInvitation, SphereMembership
from ludamus.mills.team import token_hash
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import (
    InvitationPreviewDTO,
    JoinPageDTO,
    SphereInvitationDTO,
    TeamMemberDTO,
)
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


def _invitation(sphere, *, role=SphereRole.MANAGER, token="tok", **fields):
    return SphereInvitation.objects.create(
        sphere=sphere,
        role=role,
        token_hash=token_hash(token),
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
        invitation = _invitation(
            sphere, role=SphereRole.COMMS, created_by=manager, note="Kasia, programme"
        )
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
                        note="Kasia, programme",
                        invited_by="Test User",
                        creation_time=invitation.creation_time,
                        expires_at=invitation.expires_at,
                    )
                ],
                "invitation_form": ANY,
                "issued_link": None,
            },
        )

    def test_a_new_link_is_shown_once_and_never_stored(
        self, authenticated_client, manager, sphere
    ):
        authenticated_client.post(INVITE_URL, data={"role": "comms"})
        invitation = SphereInvitation.objects.get(sphere=sphere)

        first = authenticated_client.get(TEAM_URL)
        again = authenticated_client.get(TEAM_URL)

        issued = first.context["issued_link"]
        assert issued.pk == invitation.pk
        token = issued.path.removeprefix("/multiverse/join/").removesuffix("/")
        assert len(token) == URLSAFE_32_BYTES_LENGTH
        assert invitation.token_hash == token_hash(token)
        assert token not in invitation.token_hash
        assert again.context["issued_link"] is None

    def test_a_stored_hash_is_not_a_link(self, authenticated_client, sphere):
        invitation = _invitation(sphere)

        response = authenticated_client.get(_join_url(invitation.token_hash))

        assert response.status_code == HTTPStatus.GONE

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
                "issued_link": None,
            },
        )


class TestTeamInviteActionView:
    def test_manager_creates_a_week_long_link_for_the_role(
        self, authenticated_client, manager, sphere
    ):
        response = authenticated_client.post(
            INVITE_URL, data={"role": "comms", "note": "  Kasia, programme "}
        )

        invitation = SphereInvitation.objects.get(sphere=sphere)
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Invitation link ready. Copy it below and send it to "
                        "Kasia, programme."
                    ),
                )
            ],
        )
        assert invitation.role == SphereRole.COMMS
        assert invitation.note == "Kasia, programme"
        assert invitation.created_by == manager
        lifetime = invitation.expires_at - invitation.creation_time
        assert timedelta(days=7) - timedelta(minutes=1) < lifetime <= timedelta(days=7)

    def test_the_note_is_optional(self, authenticated_client, manager, sphere):
        response = authenticated_client.post(INVITE_URL, data={"role": "manager"})

        invitation = SphereInvitation.objects.get(sphere=sphere)
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Invitation link ready. Copy it below and send it to the "
                        "person you're inviting."
                    ),
                )
            ],
        )
        assert not invitation.note

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
            messages=[(messages.SUCCESS, "Invitation withdrawn.")],
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

        response = authenticated_client.post(self._url(accepted))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=TEAM_URL,
            messages=[
                (messages.ERROR, "That invitation was already used or has expired.")
            ],
        )
        assert SphereInvitation.objects.filter(pk=accepted.pk).exists()

    def test_comms_member_cannot_withdraw(self, authenticated_client, comms, sphere):
        invitation = _invitation(sphere)

        response = authenticated_client.post(self._url(invitation))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert SphereInvitation.objects.filter(pk=invitation.pk).exists()


def _join_page(sphere, *, invitation=None, member_role=None):
    return {
        "page": JoinPageDTO(
            sphere_name=sphere.name, invitation=invitation, member_role=member_role
        )
    }


class TestJoinSpherePageView:
    def test_a_signed_out_visitor_sees_the_offer_before_logging_in(
        self, client, sphere
    ):
        _invitation(sphere, created_by=UserFactory(name="Ola Organizatorka"))

        response = client.get(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/join.html",
            context_data=_join_page(
                sphere,
                invitation=InvitationPreviewDTO(
                    role=SphereRole.MANAGER, invited_by="Ola Organizatorka"
                ),
            ),
        )

    def test_accepting_needs_an_account(self, client, sphere):
        _invitation(sphere)

        response = client.post(_join_url("tok"))

        assert_login_required(response, _join_url("tok"))
        assert SphereInvitation.objects.get().accepted_at is None

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
            context_data=_join_page(
                sphere,
                invitation=InvitationPreviewDTO(
                    role=SphereRole.COMMS, invited_by="Ola Organizatorka"
                ),
            ),
        )

    def test_a_nameless_inviter_is_not_given_a_made_up_name(
        self, authenticated_client, sphere
    ):
        _invitation(sphere, created_by=UserFactory(name=""))

        response = authenticated_client.get(_join_url("tok"))

        assert response.context["page"].invitation == InvitationPreviewDTO(
            role=SphereRole.MANAGER, invited_by=""
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
    @pytest.mark.parametrize("method", ("get", "post"))
    def test_a_spent_link_says_so_and_grants_nothing(
        self, authenticated_client, active_user, sphere, fields, method
    ):
        _invitation(sphere, **fields)

        response = getattr(authenticated_client, method)(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.GONE,
            template_name="multiverse/join.html",
            context_data=_join_page(sphere),
        )
        assert not SphereMembership.objects.filter(user=active_user).exists()

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_another_spheres_link_grants_nothing_here(
        self, authenticated_client, active_user, sphere, method
    ):
        _invitation(SphereFactory())

        response = getattr(authenticated_client, method)(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.GONE,
            template_name="multiverse/join.html",
            context_data=_join_page(sphere),
        )
        assert not SphereMembership.objects.filter(user=active_user).exists()
        assert SphereInvitation.objects.get().accepted_at is None

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_a_member_is_told_so_and_the_link_stays_unspent(
        self, authenticated_client, comms, sphere, method
    ):
        invitation = _invitation(sphere, role=SphereRole.MANAGER)

        response = getattr(authenticated_client, method)(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/join.html",
            context_data=_join_page(
                sphere,
                invitation=InvitationPreviewDTO(role=SphereRole.MANAGER, invited_by=""),
                member_role=SphereRole.COMMS,
            ),
        )
        assert SphereMembership.objects.get(user=comms).role == SphereRole.COMMS
        invitation.refresh_from_db()
        assert invitation.accepted_at is None

    def test_a_member_reopening_their_spent_link_is_told_they_are_in(
        self, authenticated_client, comms, sphere
    ):
        _invitation(sphere, accepted_at=datetime.now(UTC), accepted_by=comms)

        response = authenticated_client.get(_join_url("tok"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/join.html",
            context_data=_join_page(sphere, member_role=SphereRole.COMMS),
        )

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

    def test_a_private_spheres_dead_link_explains_instead_of_404ing(
        self, authenticated_client, sphere
    ):
        sphere.visibility = "private"
        sphere.save(update_fields=["visibility"])

        response = authenticated_client.get(_join_url("nope"))

        assert_response(
            response,
            HTTPStatus.GONE,
            template_name="multiverse/join.html",
            context_data=_join_page(sphere),
        )
