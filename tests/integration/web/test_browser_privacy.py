from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from ludamus.inits.browser_privacy import BrowserPrivacyMiddleware
from ludamus.inits.services import Services
from ludamus.links.db.django.models import User


@pytest.mark.parametrize("age_band", ("unknown", "13_15", "16_plus"))
def test_cookie_exposes_only_current_eligible_revision(active_user, settings, age_band):
    settings.ROOT_DOMAIN = "localhost:8000"
    settings.SESSION_COOKIE_DOMAIN = None
    User.objects.filter(pk=active_user.pk).update(age_band=age_band)
    active_user.refresh_from_db()
    request = RequestFactory().get("/")
    request.user = active_user
    request.services = Services()

    response = BrowserPrivacyMiddleware(lambda _: HttpResponse())(request)

    cookie = response.cookies["ludamus.privacy"]
    assert cookie.value == (
        str(active_user.privacy_revision) if age_band == "16_plus" else "off"
    )
    assert cookie["domain"] == "localhost"
    assert cookie["path"] == "/"
    assert cookie["samesite"] == "Lax"
    assert not cookie["httponly"]


@pytest.mark.parametrize("age_band", ("13_15", "16_plus"))
def test_cookie_uses_response_time_state_not_the_authenticated_user_cache(
    active_user, age_band
):
    User.objects.filter(pk=active_user.pk).update(age_band="16_plus")
    active_user.refresh_from_db()
    request = RequestFactory().get("/")
    request.user = active_user
    request.services = Services()
    revision = uuid4()

    def change_age(_request):
        User.objects.filter(pk=active_user.pk).update(
            age_band=age_band, privacy_revision=revision
        )
        return HttpResponse()

    response = BrowserPrivacyMiddleware(change_age)(request)

    assert response.cookies["ludamus.privacy"].value == (
        str(revision) if age_band == "16_plus" else "off"
    )
    assert active_user.age_band == "16_plus"
    assert active_user.privacy_revision != revision


def test_cookie_uses_explicit_shared_session_domain(active_user, settings):
    settings.SESSION_COOKIE_DOMAIN = ".example.test"
    request = RequestFactory().get("/")
    request.user = active_user
    request.services = Services()

    response = BrowserPrivacyMiddleware(lambda _: HttpResponse())(request)

    assert response.cookies["ludamus.privacy"]["domain"] == ".example.test"


def test_signed_out_response_revokes_existing_cookie():
    request = RequestFactory().get("/", HTTP_COOKIE="ludamus.privacy=old-revision")
    request.user = AnonymousUser()
    request.services = Services()

    response = BrowserPrivacyMiddleware(lambda _: HttpResponse())(request)

    assert response.cookies["ludamus.privacy"].value == "off"


def test_correct_cookie_does_not_emit_redundant_set_cookie():
    request = RequestFactory().get("/", HTTP_COOKIE="ludamus.privacy=off")
    request.user = AnonymousUser()
    request.services = Services()

    response = BrowserPrivacyMiddleware(lambda _: HttpResponse())(request)

    assert "ludamus.privacy" not in response.cookies


def test_static_response_does_not_overwrite_privacy_cookie(settings):
    request = RequestFactory().get(f"{settings.STATIC_URL}site.css")

    response = BrowserPrivacyMiddleware(lambda _: HttpResponse())(request)

    assert "ludamus.privacy" not in response.cookies
