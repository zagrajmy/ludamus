import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from secrets import token_urlsafe
from unittest.mock import patch

import pytest
from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse
from workos import BadRequestError

from ludamus.links.db.django.models import User
from ludamus.pacts.crowd import MAX_AVATAR_URL_LENGTH
from tests.integration.utils import assert_response
from tests.integration.web.crowd.workos_responses import (
    AUTHENTICATE,
    SESSION_ID,
    authenticate_response,
)

PROFILE_URL = "http://testserver/crowd/profile/?next=%2F"
COMPLETE_PROFILE = [(messages.SUCCESS, "Please complete your profile.")]
EXPIRED = [(messages.ERROR, "Authentication session expired. Please try again.")]


def _valid_state(redirect_to=None):
    state_token = token_urlsafe(32)
    state_data = {
        "redirect_to": redirect_to,
        "created_at": datetime.now(UTC).isoformat(),
    }
    cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)
    return state_token


@pytest.fixture(name="authenticate")
def authenticate_fixture():
    with patch(AUTHENTICATE) as authenticate:
        yield authenticate


@pytest.fixture(name="workos_id")
def workos_id_fixture(faker):
    return f"user_{faker.uuid4().replace('-', '').upper()}"


class TestLoginCallbackActionView:
    URL = reverse("web:crowd:auth:login-callback")

    def test_ok(self, authenticate, client, workos_id):
        authenticate.return_value = authenticate_response(workos_id)
        state_token = _valid_state()

        response = client.get(self.URL, {"state": state_token, "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        authenticate.assert_called_once_with(code="abc")
        user = User.objects.get()
        assert user.username == f"workos|{workos_id}"
        assert user.slug == workos_id.lower()
        assert not user.has_usable_password()
        assert client.session["workos_session_id"] == SESSION_ID
        assert cache.get(f"oauth_state:{state_token}") is None

    def test_ok_clear_anonymous_session(self, authenticate, client, workos_id):
        session = client.session
        session["anonymous_user_code"] = 123
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = 456
        session.save()
        authenticate.return_value = authenticate_response(workos_id)

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert client.session.get("anonymous_user_code") is None
        assert client.session.get("anonymous_enrollment_active") is None
        assert client.session.get("anonymous_event_id") is None

    def test_ok_redirect_to(self, authenticate, client, workos_id):
        authenticate.return_value = authenticate_response(workos_id)
        state_token = _valid_state("https://www.testserver/a/b/c")

        response = client.get(self.URL, {"state": state_token, "code": "abc"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="https://www.testserver/crowd/profile/?next=%2F",
            messages=COMPLETE_PROFILE,
        )

    def test_ok_already_authenticated(self, authenticated_client):
        response = authenticated_client.get(self.URL, {"state": _valid_state()})

        assert_response(response, HTTPStatus.FOUND, url="http://testserver/")

    def test_ok_already_authenticated_redirect_to(self, authenticated_client):
        redirect_to = "https://sphere.testserver/a/b/"

        response = authenticated_client.get(
            self.URL, {"state": _valid_state(redirect_to)}
        )

        assert_response(response, HTTPStatus.FOUND, url=redirect_to)

    def test_ok_already_authenticated_relative_redirect_to(self, authenticated_client):
        response = authenticated_client.get(
            self.URL, {"state": _valid_state("/event/foo/")}
        )

        assert_response(response, HTTPStatus.FOUND, url="/event/foo/")

    @pytest.mark.parametrize(
        "redirect_to", ("https://evil.example.com/phish/", "//evil.example.com/phish/")
    )
    def test_external_redirect_to_dropped(self, authenticated_client, redirect_to):
        response = authenticated_client.get(
            self.URL, {"state": _valid_state(redirect_to)}
        )

        assert_response(response, HTTPStatus.FOUND, url="http://testserver/")

    def test_external_redirect_to_dropped_on_login(
        self, authenticate, client, workos_id
    ):
        authenticate.return_value = authenticate_response(workos_id)
        state_token = _valid_state("https://evil.example.com/a/b/c")

        response = client.get(self.URL, {"state": state_token, "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )

    def test_ok_complete_user(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        authenticate.return_value = authenticate_response(workos_id)
        complete_user_factory(username=f"workos|{workos_id}", slug="me")

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )

    def test_ok_long_id_truncates_slug(self, authenticate, client):
        workos_id = "user_" + "X" * 60
        authenticate.return_value = authenticate_response(workos_id)

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        user = User.objects.get(username=f"workos|{workos_id}")
        assert len(user.slug) <= User._meta.get_field("slug").max_length

    def test_ok_slug_collision_creates_distinct_account(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        complete_user_factory(username="someone-else", slug=workos_id.lower())
        authenticate.return_value = authenticate_response(workos_id)

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert User.objects.get(username=f"workos|{workos_id}").slug != (
            workos_id.lower()
        )

    def test_error_rejected_code(self, authenticate, client):
        authenticate.side_effect = BadRequestError("invalid_grant", status_code=400)

        response = client.get(self.URL, {"state": _valid_state(), "code": "stale"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, "Authentication failed")],
        )
        assert not User.objects.exists()

    def test_error_from_authkit_goes_to_error_page(self, authenticate, client):
        response = client.get(
            self.URL, {"state": _valid_state(), "error": "access_denied"}
        )

        assert_response(
            response, HTTPStatus.FOUND, url="/auth-error/?error=access_denied"
        )
        authenticate.assert_not_called()

    def test_error_missing_state(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (
                    messages.ERROR,
                    "Invalid authentication request: missing state parameter",
                )
            ],
        )

    def test_error_invalid_state(self, client):
        response = client.get(self.URL, {"state": "invalid_state_token"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=EXPIRED
        )

    def test_error_expired_state(self, authenticate, client):
        state_token = token_urlsafe(32)
        state_data = {
            "redirect_to": None,
            "created_at": (datetime.now(UTC) - timedelta(minutes=15)).isoformat(),
        }
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)

        response = client.get(self.URL, {"state": state_token, "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=EXPIRED
        )
        authenticate.assert_not_called()

    def test_error_replay_attack(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        authenticate.return_value = authenticate_response(workos_id)
        complete_user_factory(username=f"workos|{workos_id}", slug="me")
        state_token = _valid_state()

        response = client.get(self.URL, {"state": state_token, "code": "abc"})
        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )

        response = client.get(self.URL, {"state": state_token, "code": "abc"})
        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=EXPIRED
        )

    @pytest.mark.parametrize(
        "state_data", ({"invalid": "data"}, {"created_at": "invalid_datetime_format"})
    )
    def test_invalid_authentication_state(self, client, state_data):
        state_token = token_urlsafe(20)
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[(messages.ERROR, "Invalid authentication state")],
        )

    def test_ok_updates_existing_user_fields(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        username = f"workos|{workos_id}"
        complete_user_factory(
            username=username,
            slug="me",
            name="",
            email="old@example.com",
            avatar_url="https://example.com/old.png",
        )
        authenticate.return_value = authenticate_response(
            workos_id,
            email="new@example.com",
            profile_picture_url="https://example.com/new.png",
            first_name="New",
            last_name="Name",
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.email == "new@example.com"
        assert user.avatar_url == "https://example.com/new.png"
        assert user.name == "New Name"

    def test_ok_overlong_picture_dropped_on_create(
        self, authenticate, client, workos_id
    ):
        picture = f"https://example.com/{'a' * MAX_AVATAR_URL_LENGTH}.png"
        authenticate.return_value = authenticate_response(
            workos_id, profile_picture_url=picture
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert not User.objects.get(username=f"workos|{workos_id}").avatar_url

    def test_ok_overlong_picture_dropped_on_update(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        username = f"workos|{workos_id}"
        complete_user_factory(
            username=username, slug="me", avatar_url="https://example.com/old.png"
        )
        picture = f"https://example.com/{'a' * MAX_AVATAR_URL_LENGTH}.png"
        authenticate.return_value = authenticate_response(
            workos_id, profile_picture_url=picture
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.avatar_url == "https://example.com/old.png"

    def test_ok_max_length_picture_stored_on_create(
        self, authenticate, client, workos_id
    ):
        prefix, suffix = "https://example.com/", ".png"
        filler = "a" * (MAX_AVATAR_URL_LENGTH - len(prefix) - len(suffix))
        picture = f"{prefix}{filler}{suffix}"
        authenticate.return_value = authenticate_response(
            workos_id, profile_picture_url=picture
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert User.objects.get(username=f"workos|{workos_id}").avatar_url == picture

    def test_ok_updates_email_without_name(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        username = f"workos|{workos_id}"
        complete_user_factory(
            username=username, slug="me", name="Existing Name", email="old@example.com"
        )
        authenticate.return_value = authenticate_response(
            workos_id, email="new@example.com", first_name="Other"
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.email == "new@example.com"
        assert user.name == "Existing Name"

    def test_ok_create_strips_duplicate_email(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        complete_user_factory(username="workos|someone", email="taken@example.com")
        authenticate.return_value = authenticate_response(
            workos_id, email="taken@example.com"
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert not User.objects.get(username=f"workos|{workos_id}").email

    def test_ok_update_strips_duplicate_email(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        complete_user_factory(username="workos|someone", email="taken@example.com")
        username = f"workos|{workos_id}"
        complete_user_factory(username=username, slug="me", email="old@example.com")
        authenticate.return_value = authenticate_response(
            workos_id, email="taken@example.com"
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        assert User.objects.get(username=username).email == "old@example.com"


class TestLegacyAuth0Accounts:
    URL = reverse("web:crowd:auth:login-callback")

    def test_imported_user_keeps_their_account(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        legacy = complete_user_factory(
            username="auth0|google-oauth2|1234", slug="legacy", name="Old Timer"
        )
        authenticate.return_value = authenticate_response(
            workos_id, external_id="google-oauth2|1234"
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        legacy.refresh_from_db()
        assert legacy.username == f"workos|{workos_id}"
        assert User.objects.count() == 1

    def test_verified_email_links_account_the_import_missed(
        self, authenticate, client, complete_user_factory, workos_id
    ):
        legacy = complete_user_factory(
            username="auth0|auth0|abc", slug="legacy", email="me@example.com"
        )
        authenticate.return_value = authenticate_response(
            workos_id, email="ME@example.com"
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        legacy.refresh_from_db()
        assert legacy.username == f"workos|{workos_id}"

    @pytest.mark.parametrize(
        ("username", "verified"),
        (("auth0|auth0|abc", False), ("workos|user_OTHER", True)),
    )
    def test_email_alone_does_not_link(
        self, authenticate, client, complete_user_factory, workos_id, username, verified
    ):
        complete_user_factory(username=username, slug="other", email="me@example.com")
        authenticate.return_value = authenticate_response(
            workos_id, email="me@example.com", email_verified=verified
        )

        response = client.get(self.URL, {"state": _valid_state(), "code": "abc"})

        assert_response(
            response, HTTPStatus.FOUND, url=PROFILE_URL, messages=COMPLETE_PROFILE
        )
        assert User.objects.get(slug="other").username == username
        assert not User.objects.get(username=f"workos|{workos_id}").email
