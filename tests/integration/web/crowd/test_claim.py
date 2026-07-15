import json
from datetime import UTC, datetime
from http import HTTPStatus
from secrets import token_urlsafe
from unittest.mock import patch

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.urls import reverse

from ludamus.adapters.db.django.models import User, UserType
from ludamus.links.db.django.crowd import ClaimRepository
from ludamus.pacts.crowd import ClaimableProfileDTO
from ludamus.pacts.party import PartyConsentMode
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response


def _companion(
    *, manager, name="Kiddo", slug="kiddo", token="", username="connected|x"
):
    return UserFactory(
        username=username,
        slug=slug,
        name=name,
        email="",
        user_type=UserType.CONNECTED,
        manager=manager,
        claim_token=token,
        password=make_password(None),
    )


def _active(*, username, slug, name="Owner"):
    return UserFactory(
        username=username,
        slug=slug,
        name=name,
        user_type=UserType.ACTIVE,
        password=make_password(None),
    )


class TestProfileCompanionClaimLinkActionView:
    def test_post_issues_link(self, authenticated_client, companion):
        url = reverse(
            "web:crowd:profile-companions-claim-link", kwargs={"slug": companion.slug}
        )

        response = authenticated_client.post(url)

        companion.refresh_from_db()
        assert companion.claim_token
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/crowd/profile/parties/",
            messages=[(messages.SUCCESS, "Claim link created.")],
        )

    def test_page_offers_copy_button_for_pending_link(
        self, authenticated_client, companion
    ):
        companion.claim_token = "tok"
        companion.save()
        claim_path = reverse("web:crowd:claim", kwargs={"token": "tok"})

        response = authenticated_client.get(reverse("web:crowd:profile-parties"))

        content = response.content.decode()
        assert f'data-copy="{claim_path}"' in content
        assert "data-copy-origin" in content

    def test_post_rejects_other_managers_user(self, authenticated_client):
        other = _active(username="other", slug="other")
        kid = _companion(manager=other, slug="otherkid", username="connected|other")
        url = reverse(
            "web:crowd:profile-companions-claim-link", kwargs={"slug": kid.slug}
        )

        response = authenticated_client.post(url)

        kid.refresh_from_db()
        assert not kid.claim_token
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/crowd/profile/parties/",
            messages=[
                (messages.ERROR, "Could not create a claim link for this person.")
            ],
        )


class TestClaimPageView:
    def test_get_shows_landing(self, client, active_user):
        kid = _companion(manager=active_user, token="tok")
        url = reverse("web:crowd:claim", kwargs={"token": "tok"})

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/claim.html",
            context_data={
                "claimable": ClaimableProfileDTO(
                    name=kid.name, slug=kid.slug, manager_name=active_user.name
                ),
                "token": "tok",
            },
        )

    def test_get_invalid_token(self, client):
        url = reverse("web:crowd:claim", kwargs={"token": "nope"})

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[
                (messages.ERROR, "This claim link is invalid or has already been used.")
            ],
        )

    def test_get_already_signed_in_is_refused(self, authenticated_client):
        url = reverse("web:crowd:claim", kwargs={"token": "tok"})

        response = authenticated_client.get(url)

        expected = (
            "You're already signed in. Log out first to claim this "
            "profile into a new account."
        )
        assert_response(
            response, HTTPStatus.FOUND, url="/", messages=[(messages.INFO, expected)]
        )

    def test_post_stashes_token_and_redirects_to_login(self, client, active_user):
        _companion(manager=active_user, token="tok")
        url = reverse("web:crowd:claim", kwargs={"token": "tok"})

        response = client.post(url)

        assert client.session["pending_claim_token"] == "tok"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/crowd/auth0/do/login?next=%2Fcrowd%2Fprofile%2F",
        )

    def test_post_already_signed_in_is_refused(self, authenticated_client):
        url = reverse("web:crowd:claim", kwargs={"token": "tok"})

        response = authenticated_client.post(url)

        assert "pending_claim_token" not in authenticated_client.session
        assert_response(response, HTTPStatus.FOUND, url="/")

    def test_post_invalid_token(self, client):
        url = reverse("web:crowd:claim", kwargs={"token": "nope"})

        response = client.post(url)

        assert "pending_claim_token" not in client.session
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[
                (messages.ERROR, "This claim link is invalid or has already been used.")
            ],
        )


class TestClaimRedemptionOnLogin:
    URL = reverse("web:crowd:auth0:login-callback")

    @staticmethod
    def _valid_state():
        state_token = token_urlsafe(32)
        cache.set(
            f"oauth_state:{state_token}",
            json.dumps(
                {"redirect_to": None, "created_at": datetime.now(UTC).isoformat()}
            ),
            timeout=600,
        )
        return state_token

    def _arm_claim(self, client, token):
        session = client.session
        session["pending_claim_token"] = token
        session.save()

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_converts_managed_row_into_account(self, token_mock, client, faker):
        manager = _active(username="mgr", slug="mgr")
        kid = _companion(manager=manager, token="claimtok", username="connected|kid")
        sponsor_user(leader=manager, member=kid)
        sub = faker.uuid4()
        token_mock.return_value = {"userinfo": {"sub": sub}}
        self._arm_claim(client, "claimtok")
        state_token = self._valid_state()

        response = client.get(self.URL, {"state": state_token})

        kid.refresh_from_db()
        assert kid.user_type == UserType.ACTIVE
        assert kid.username == f"auth0|{sub}"
        assert not kid.claim_token
        # The membership survives the claim but now needs the member's accept.
        membership = kid.party_memberships.get()
        assert membership.consent_mode == PartyConsentMode.ACCEPT_INVITES
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (messages.SUCCESS, "Profile claimed — it is now your own account.")
            ],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_spent_token_falls_through_to_normal_login(self, token_mock, client, faker):
        sub = faker.uuid4()
        token_mock.return_value = {"userinfo": {"sub": sub}}
        self._arm_claim(client, "spent-or-bogus")
        state_token = self._valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert User.objects.filter(
            username=f"auth0|{sub}", user_type=UserType.ACTIVE
        ).exists()
        # No claim messages — just the ordinary fresh-account onboarding nudge.
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/?next=%2Fevents%2F",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_refuses_when_recipient_already_has_account(
        self, token_mock, client, faker
    ):
        sub = faker.uuid4()
        _active(username=f"auth0|{sub}", slug="existing", name="Me")
        manager = _active(username="mgr", slug="mgr")
        kid = _companion(manager=manager, token="claimtok", username="connected|kid")
        token_mock.return_value = {"userinfo": {"sub": sub}}
        self._arm_claim(client, "claimtok")
        state_token = self._valid_state()

        response = client.get(self.URL, {"state": state_token})

        kid.refresh_from_db()
        assert kid.user_type == UserType.CONNECTED
        assert kid.claim_token == "claimtok"
        expected = (
            "You already have an account, so this profile can't be moved "
            "into it. Ask the person who invited you to enroll you directly."
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[(messages.INFO, expected)],
        )


class TestClaimRepository:
    def test_read_claimable_empty_token_matches_nothing(self):
        # Rows without a pending claim carry claim_token="", so an empty token
        # must short-circuit instead of matching every such row.
        manager = _active(username="mgr", slug="mgr")
        _companion(manager=manager, username="connected|kid")

        assert ClaimRepository.read_claimable("") is None

    def test_read_claimable_ignores_non_companion_row(self):
        owner = _active(username="owner", slug="owner")
        owner.claim_token = "tok"
        owner.save()

        assert ClaimRepository.read_claimable("tok") is None

    def test_convert_empty_token_converts_nothing(self):
        manager = _active(username="mgr", slug="mgr")
        kid = _companion(manager=manager, username="connected|kid")

        assert ClaimRepository.convert(token="", username="auth0|sneak") is None
        kid.refresh_from_db()
        assert kid.user_type == UserType.CONNECTED
        assert kid.manager_id == manager.pk
        assert not kid.party_memberships.exists()

    def test_convert_is_single_use(self):
        manager = _active(username="mgr", slug="mgr")
        kid = _companion(manager=manager, token="tok", username="connected|kid")

        slug = ClaimRepository.convert(token="tok", username="auth0|new")

        assert slug == kid.slug
        kid.refresh_from_db()
        assert kid.user_type == UserType.ACTIVE
        assert kid.manager_id is None
        assert not kid.claim_token
        # The token is spent: a second redemption finds nothing.
        assert ClaimRepository.convert(token="tok", username="auth0|other") is None
        assert ClaimRepository.read_claimable("tok") is None
