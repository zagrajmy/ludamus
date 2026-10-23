import json
from datetime import UTC, datetime
from http import HTTPStatus
from secrets import token_urlsafe
from unittest.mock import ANY, patch

import pytest
from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse

from ludamus.links.db.django.models import SphereSubscription, User
from tests.integration.conftest import SessionParticipationFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
)

CALLBACK_URL = reverse("web:crowd:auth0:login-callback")
GATE_URL = reverse("web:crowd:auth0:signup-age")
PROFILE_AGE_URL = reverse("user:profile-age-range")
GUARDIAN_CONTEXT = {
    "min_age": 13,
    "guardian_login_url": (
        "https://auth0.example.com/v2/logout?returnTo=http%3A%2F%2Ftestserver"
        "%2Fcrowd%2Fauth0%2Fdo%2Flogout%2Fredirect%3Flast_domain%3Dtestserver"
        "%26redirect_to%3D%2Fcrowd%2Fauth0%2Fdo%2Flogin"
        "&client_id=test-auth0-client-id"
    ),
}


def _reach_gate(client, sub):
    state_token = token_urlsafe(32)
    cache.set(
        f"oauth_state:{state_token}",
        json.dumps({"redirect_to": None, "created_at": datetime.now(UTC).isoformat()}),
        timeout=600,
    )
    with patch(
        "ludamus.gates.web.django.crowd.auth.oauth.auth0.authorize_access_token",
        return_value={"userinfo": {"sub": sub}},
    ):
        return client.get(CALLBACK_URL, {"state": state_token})


def _answer(client, age_band):
    page = client.get(GATE_URL)
    token = page.context_data["form"]["confirmation_token"].value()
    return client.post(GATE_URL, {"age_band": age_band, "confirmation_token": token})


def _update(client, age_band):
    return client.post(PROFILE_AGE_URL, {"age_band": age_band})


class TestSignupAgeGate:
    def test_signed_in_account_does_not_reach_the_signup_gate(
        self, authenticated_client
    ):
        response = authenticated_client.get(GATE_URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_first_sign_in_stops_at_gate_without_an_account(self, client, faker):
        response = _reach_gate(client, faker.uuid4())

        assert_response(response, HTTPStatus.FOUND, url=f"http://testserver{GATE_URL}")
        assert not User.objects.exists()

    def test_gate_asks_for_an_age_range(self, client, faker):
        _reach_gate(client, faker.uuid4())

        response = client.get(GATE_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/signup_age.html",
            context_data={"form": ANY},
        )

    def test_gate_without_pending_sign_in_goes_home(self, client):
        assert_response(
            client.get(GATE_URL), HTTPStatus.FOUND, url=reverse("web:index")
        )

    def test_under_thirteen_creates_nothing_and_clears_pending_claim(
        self, client, faker
    ):
        session = client.session
        session["pending_claim_token"] = "claim-token"
        session.save()
        _reach_gate(client, faker.uuid4())

        response = _answer(client, "under_13")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/signup_guardian.html",
            context_data=GUARDIAN_CONTEXT,
        )
        assert not User.objects.exists()
        assert "pending_signup" not in client.session
        assert "pending_claim_token" not in client.session

    def test_expired_form_can_be_restarted(self, client, faker):
        _reach_gate(client, faker.uuid4())
        with patch("django.core.signing.time.time", return_value=1):
            old_token = (
                client.get(GATE_URL).context_data["form"]["confirmation_token"].value()
            )

        response = client.post(
            GATE_URL, {"age_band": "13_15", "confirmation_token": old_token}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=GATE_URL,
            messages=[
                (
                    messages.ERROR,
                    "This age confirmation has expired. Choose your age range again.",
                )
            ],
        )
        assert not User.objects.exists()
        _answer(client, "13_15")
        assert User.objects.get().age_band == "13_15"

    @pytest.mark.parametrize("age_band", ("13_15", "16_plus"))
    def test_confirmed_age_creates_one_independent_account(
        self, client, faker, age_band
    ):
        sub = faker.uuid4()
        _reach_gate(client, sub)

        _answer(client, age_band)
        replay = client.post(GATE_URL, {"age_band": age_band})

        user = User.objects.get()
        assert user.username == f"auth0|{sub}"
        assert user.age_band == age_band
        assert client.session["_auth_user_id"] == str(user.pk)
        assert_response(
            replay,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.SUCCESS, "Please complete your profile.")],
        )

    def test_invalid_choice_preserves_the_pending_sign_in(self, client, faker):
        _reach_gate(client, faker.uuid4())

        response = _answer(client, "maybe")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/signup_age.html",
            context_data={
                "form": FormErrorsMatcher(
                    age_band=[
                        (
                            "Select a valid choice. "
                            "maybe is not one of the available choices."
                        )
                    ]
                )
            },
        )
        assert not User.objects.exists()
        assert "pending_signup" in client.session

    def test_form_cannot_confirm_a_later_identity(self, client, faker):
        _reach_gate(client, faker.uuid4())
        old_token = (
            client.get(GATE_URL).context_data["form"]["confirmation_token"].value()
        )
        _reach_gate(client, faker.uuid4())

        response = client.post(
            GATE_URL, {"age_band": "16_plus", "confirmation_token": old_token}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=GATE_URL,
            messages=[
                (
                    messages.ERROR,
                    "This age confirmation has expired. Choose your age range again.",
                )
            ],
        )
        assert not User.objects.exists()

    def test_later_login_discards_pending_signup(self, client, faker):
        existing_sub = faker.uuid4()
        User.objects.create(
            username=f"auth0|{existing_sub}", slug="existing", name="Existing"
        )
        _reach_gate(client, faker.uuid4())
        old_token = (
            client.get(GATE_URL).context_data["form"]["confirmation_token"].value()
        )
        _reach_gate(client, existing_sub)

        response = client.post(
            GATE_URL, {"age_band": "16_plus", "confirmation_token": old_token}
        )

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
        assert User.objects.get().age_band == "unknown"
        assert "pending_signup" not in client.session


class TestProfileAgeRange:
    def test_requires_login(self, client):
        assert_login_required(client.get(PROFILE_AGE_URL), PROFILE_AGE_URL)

    def test_asks_a_signed_in_account_for_its_range(self, authenticated_client):
        response = authenticated_client.get(PROFILE_AGE_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/user/age_range.html",
            context_data={"form": ANY, "profile_active_tab": "privacy"},
        )

    def test_invalid_choice_changes_nothing(self, authenticated_client, active_user):
        response = _update(authenticated_client, "maybe")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/user/age_range.html",
            context_data={
                "form": FormErrorsMatcher(
                    age_band=[
                        (
                            "Select a valid choice. "
                            "maybe is not one of the available choices."
                        )
                    ]
                ),
                "profile_active_tab": "privacy",
            },
        )
        active_user.refresh_from_db()
        assert active_user.age_band == "unknown"

    def test_existing_under_thirteen_account_cannot_sign_back_in(
        self, authenticated_client, active_user, faker
    ):
        sub = faker.uuid4()
        User.objects.filter(pk=active_user.pk).update(username=f"auth0|{sub}")

        response = _update(authenticated_client, "under_13")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/signup_guardian.html",
            context_data=GUARDIAN_CONTEXT,
        )
        active_user.refresh_from_db()
        assert active_user.is_active is False
        assert "_auth_user_id" not in authenticated_client.session

        response = _reach_gate(authenticated_client, sub)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/",
            messages=[
                (messages.ERROR, "This account is inactive. Contact support for help.")
            ],
        )
        assert "_auth_user_id" not in authenticated_client.session

    def test_confirming_unknown_age_does_not_reactivate_old_marketing(
        self, authenticated_client, active_user, non_root_sphere
    ):
        SphereSubscription.objects.create(user=active_user, sphere=non_root_sphere)

        _update(authenticated_client, "16_plus")

        active_user.refresh_from_db()
        assert active_user.age_band == "16_plus"
        assert not SphereSubscription.objects.filter(user=active_user).exists()

    def test_existing_account_can_confirm_age_without_losing_bookings(
        self, authenticated_client, active_user, non_root_sphere
    ):
        SphereSubscription.objects.create(user=active_user, sphere=non_root_sphere)
        booking = SessionParticipationFactory(user=active_user, status="confirmed")

        response = _update(authenticated_client, "13_15")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("user:profile-privacy"),
            messages=[
                (messages.SUCCESS, "Age range saved. Your bookings are unchanged.")
            ],
        )
        active_user.refresh_from_db()
        assert active_user.age_band == "13_15"
        booking.refresh_from_db()
        assert booking.user_id == active_user.pk
        assert booking.status == "confirmed"
        assert not SphereSubscription.objects.filter(user=active_user).exists()
