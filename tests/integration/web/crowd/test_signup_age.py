import json
from datetime import UTC, datetime
from http import HTTPStatus
from secrets import token_urlsafe
from unittest.mock import patch

from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse

from ludamus.links.db.django.models import User
from tests.integration.utils import assert_response

CALLBACK_URL = reverse("web:crowd:auth0:login-callback")
GATE_URL = reverse("web:crowd:auth0:signup-age")
AUTH0_LOGOUT_URL = (
    "https://auth0.example.com/v2/logout?returnTo=http%3A%2F%2Ftestserver"
    "%2Fcrowd%2Fauth0%2Fdo%2Flogout%2Fredirect%3Flast_domain%3Dtestserver"
    "%26redirect_to%3D%2F&client_id=test-auth0-client-id"
)
UNDER_AGE_MESSAGE = (
    "No account was created. A parent or guardian can sign up and add you as "
    "a companion to sign you up for sessions."
)


def _arm_state():
    state_token = token_urlsafe(32)
    cache.set(
        f"oauth_state:{state_token}",
        json.dumps({"redirect_to": None, "created_at": datetime.now(UTC).isoformat()}),
        timeout=600,
    )
    return state_token


def _reach_gate(client, sub):
    with patch(
        "ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token",
        return_value={"userinfo": {"sub": sub}},
    ):
        return client.get(CALLBACK_URL, {"state": _arm_state()})


class TestSignupAgeGate:
    def test_first_sign_in_stops_at_gate_without_an_account(self, client, faker):
        response = _reach_gate(client, faker.uuid4())

        assert_response(response, HTTPStatus.FOUND, url=f"http://testserver{GATE_URL}")
        assert not User.objects.exists()

    def test_gate_asks_for_minimum_age(self, client, faker):
        _reach_gate(client, faker.uuid4())

        response = client.get(GATE_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/signup_age.html",
            context_data={"min_age": 16},
        )

    def test_gate_without_pending_sign_in_goes_home(self, client):
        response = client.get(GATE_URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_under_age_creates_nothing_and_signs_out_of_auth0(self, client, faker):
        session = client.session
        session["pending_claim_token"] = "claim-token"
        session.save()
        _reach_gate(client, faker.uuid4())

        response = client.post(GATE_URL, {"age": "minor"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=AUTH0_LOGOUT_URL,
            messages=[(messages.INFO, UNDER_AGE_MESSAGE)],
        )
        assert not User.objects.exists()
        assert "pending_signup" not in client.session
        assert "pending_claim_token" not in client.session

    def test_unanswered_question_keeps_the_sign_in_pending(self, client, faker):
        _reach_gate(client, faker.uuid4())

        response = client.post(GATE_URL, {"age": "maybe"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=GATE_URL,
            messages=[(messages.ERROR, "Choose one of the two answers.")],
        )
        assert not User.objects.exists()
        assert "pending_signup" in client.session

    def test_confirm_without_pending_sign_in_creates_nothing(self, client):
        response = client.post(GATE_URL, {"age": "adult"})

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
        assert not User.objects.exists()

    def test_confirmed_age_creates_the_account_once(self, client, faker):
        sub = faker.uuid4()
        _reach_gate(client, sub)

        client.post(GATE_URL, {"age": "adult"})
        replay = client.post(GATE_URL, {"age": "adult"})

        assert_response(
            replay,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )
        assert list(User.objects.values_list("username", flat=True)) == [f"auth0|{sub}"]
