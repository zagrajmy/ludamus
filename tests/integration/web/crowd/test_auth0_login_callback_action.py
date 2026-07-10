import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from secrets import token_urlsafe
from unittest.mock import patch

from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse
from django.utils.text import slugify

from ludamus.adapters.db.django.models import User
from tests.integration.utils import assert_response


class TestAuth0LoginCallbackActionView:
    URL = reverse("web:crowd:auth0:login-callback")

    @staticmethod
    def _setup_valid_state(redirect_to=None):
        state_token = token_urlsafe(32)
        state_data = {
            "redirect_to": redirect_to,
            "created_at": datetime.now(UTC).isoformat(),
        }
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)
        return state_token

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok(self, authorize_access_token_mock, client, faker):
        sub = faker.uuid4()
        authorize_access_token_mock.return_value = {"userinfo": {"sub": sub}}
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        assert User.objects.get().username == f"auth0|{sub}"
        assert cache.get(f"oauth_state:{state_token}") is None

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_clear_anonymous_session(
        self, authorize_access_token_mock, client, faker
    ):
        session = client.session
        session["anonymous_user_code"] = 123
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = 456
        session.save()
        sub = faker.uuid4()
        authorize_access_token_mock.return_value = {"userinfo": {"sub": sub}}
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        assert User.objects.get().username == f"auth0|{sub}"
        assert cache.get(f"oauth_state:{state_token}") is None
        assert client.session.get("anonymous_user_code") is None
        assert client.session.get("anonymous_enrollment_active") is None
        assert client.session.get("anonymous_event_id") is None

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_redirect_to(self, authorize_access_token_mock, client, faker):
        sub = faker.uuid4()
        authorize_access_token_mock.return_value = {"userinfo": {"sub": sub}}
        redirect_to = "https://www.testserver/a/b/c"
        state_token = self._setup_valid_state(redirect_to)

        response = client.get(self.URL, data={"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="https://www.testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        assert User.objects.get().username == f"auth0|{sub}"

    def test_ok_already_authenticated(self, authenticated_client):
        state_token = self._setup_valid_state()
        response = authenticated_client.get(self.URL, {"state": state_token})

        assert_response(response, HTTPStatus.FOUND, url="http://testserver/")

    def test_ok_already_authenticated_redirect_to(self, authenticated_client):
        redirect_to = "https://sphere.testserver/a/b/"
        state_token = self._setup_valid_state(redirect_to)
        response = authenticated_client.get(self.URL, data={"state": state_token})

        assert_response(response, HTTPStatus.FOUND, url=redirect_to)

    def test_ok_already_authenticated_relative_redirect_to(self, authenticated_client):
        state_token = self._setup_valid_state("/event/foo/")
        response = authenticated_client.get(self.URL, data={"state": state_token})

        assert_response(response, HTTPStatus.FOUND, url="/event/foo/")

    def test_external_redirect_to_dropped(self, authenticated_client):
        state_token = self._setup_valid_state("https://evil.example.com/phish/")
        response = authenticated_client.get(self.URL, data={"state": state_token})

        assert_response(response, HTTPStatus.FOUND, url="http://testserver/")

    def test_protocol_relative_redirect_to_dropped(self, authenticated_client):
        state_token = self._setup_valid_state("//evil.example.com/phish/")
        response = authenticated_client.get(self.URL, data={"state": state_token})

        assert_response(response, HTTPStatus.FOUND, url="http://testserver/")

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_external_redirect_to_dropped_on_login(
        self, authorize_access_token_mock, client, faker
    ):
        authorize_access_token_mock.return_value = {"userinfo": {"sub": faker.uuid4()}}
        state_token = self._setup_valid_state("https://evil.example.com/a/b/c")

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_complete_user(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        authorize_access_token_mock.return_value = {"userinfo": {"sub": faker.uuid4()}}
        username = (
            f'auth0|{authorize_access_token_mock.return_value["userinfo"]["sub"]}'
        )
        complete_user_factory(username=username, slug=slugify(username))
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_error_bad_token(self, authorize_access_token_mock, client):
        authorize_access_token_mock.return_value = {}
        state_token = self._setup_valid_state()
        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, "Authentication failed")],
        )

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
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (messages.ERROR, "Authentication session expired. Please try again.")
            ],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_error_expired_state(self, authorize_access_token_mock, client, faker):

        authorize_access_token_mock.return_value = {"userinfo": {"sub": faker.uuid4()}}

        state_token = token_urlsafe(32)
        state_data = {
            "redirect_to": None,
            "created_at": (datetime.now(UTC) - timedelta(minutes=15)).isoformat(),
        }
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (messages.ERROR, "Authentication session expired. Please try again.")
            ],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_error_replay_attack(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        sub_id = faker.uuid4()
        authorize_access_token_mock.return_value = {"userinfo": {"sub": sub_id}}

        username = f"auth0|{sub_id}"
        complete_user_factory(username=username, slug=slugify(username))

        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )

        response = client.get(self.URL, {"state": state_token})
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (messages.ERROR, "Authentication session expired. Please try again.")
            ],
        )

    def test_invalid_authentication_state_keyerror(self, client):
        state_token = token_urlsafe(20)
        state_data = {"invalid": "data"}
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[(messages.ERROR, "Invalid authentication state")],
        )

    def test_invalid_authentication_state_valueerror(self, client):
        state_token = token_urlsafe(20)
        state_data = {"created_at": "invalid_datetime_format"}
        cache.set(f"oauth_state:{state_token}", json.dumps(state_data), timeout=600)

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[(messages.ERROR, "Invalid authentication state")],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_updates_existing_user_fields(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        sub = faker.uuid4()
        username = f"auth0|{sub}"
        complete_user_factory(
            username=username,
            slug=slugify(username),
            name="",
            email="old@example.com",
            avatar_url="https://example.com/old.png",
        )
        authorize_access_token_mock.return_value = {
            "userinfo": {
                "sub": sub,
                "email": "new@example.com",
                "picture": "https://example.com/new.png",
                "name": "New Name",
            }
        }
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.email == "new@example.com"
        assert user.avatar_url == "https://example.com/new.png"
        assert user.name == "New Name"

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_updates_email_without_name(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        sub = faker.uuid4()
        username = f"auth0|{sub}"
        complete_user_factory(
            username=username,
            slug=slugify(username),
            name="Existing Name",
            email="old@example.com",
        )
        authorize_access_token_mock.return_value = {
            "userinfo": {"sub": sub, "email": "new@example.com"}
        }
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.email == "new@example.com"
        assert user.name == "Existing Name"

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.userinfo")
    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_token_not_dict(
        self, authorize_access_token_mock, userinfo_mock, client, faker
    ):
        sub = faker.uuid4()
        authorize_access_token_mock.return_value = "opaque-token-string"
        userinfo_mock.return_value = {"sub": sub}
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        assert User.objects.get().username == f"auth0|{sub}"

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.userinfo")
    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_error_userinfo_returns_non_dict(
        self, authorize_access_token_mock, userinfo_mock, client
    ):
        authorize_access_token_mock.return_value = "opaque-token-string"
        userinfo_mock.return_value = "not-a-dict"
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, "Authentication failed")],
        )

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_create_strips_duplicate_email(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        existing_email = "taken@example.com"
        complete_user_factory(email=existing_email)
        sub = faker.uuid4()
        authorize_access_token_mock.return_value = {
            "userinfo": {"sub": sub, "email": existing_email}
        }
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/profile/",
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        new_user = User.objects.get(username=f"auth0|{sub}")
        assert not new_user.email

    @patch("ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token")
    def test_ok_update_strips_duplicate_email(
        self, authorize_access_token_mock, client, complete_user_factory, faker
    ):
        existing_email = "taken@example.com"
        complete_user_factory(email=existing_email)
        sub = faker.uuid4()
        username = f"auth0|{sub}"
        complete_user_factory(
            username=username, slug=slugify(username), email="old@example.com"
        )
        authorize_access_token_mock.return_value = {
            "userinfo": {"sub": sub, "email": existing_email}
        }
        state_token = self._setup_valid_state()

        response = client.get(self.URL, {"state": state_token})

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/", messages=[]
        )
        user = User.objects.get(username=username)
        assert user.email == "old@example.com"
