from http import HTTPStatus
from importlib import import_module

import pytest
from django.conf import settings as django_settings
from django.contrib import messages
from django.http import HttpResponse
from django.template import engines
from django.template.response import TemplateResponse
from django.urls import path

from ludamus.gates.web.django.cache import audience_cache
from tests.integration.utils import assert_response

MAX_AGE = 60
PLAIN_TEMPLATE = engines["django"].from_string("same for everyone")
CSRF_TEMPLATE = engines["django"].from_string("<form>{% csrf_token %}</form>")


@audience_cache(max_age=MAX_AGE)
def _plain(_request):
    return HttpResponse("same for everyone")


@audience_cache(max_age=MAX_AGE)
def _template(request):
    return TemplateResponse(request, PLAIN_TEMPLATE)


@audience_cache(max_age=MAX_AGE)
def _csrf_form(request):
    return TemplateResponse(request, CSRF_TEMPLATE)


@audience_cache(max_age=MAX_AGE)
def _flash(request):
    messages.info(request, "Saved.")
    return HttpResponse("same for everyone")


urlpatterns = [
    path("audience-plain/", _plain),
    path("audience-template/", _template),
    path("audience-csrf/", _csrf_form),
    path("audience-flash/", _flash),
    *import_module(django_settings.ROOT_URLCONF).urlpatterns,
]


@pytest.mark.django_db
@pytest.mark.urls(__name__)
@pytest.mark.usefixtures("sphere")
class TestAudienceCache:
    def test_anonymous_plain_response_is_public(self, client):
        response = client.get("/audience-plain/")

        assert_response(
            response, HTTPStatus.OK, cache_control={"public", f"max-age={MAX_AGE}"}
        )
        assert "Cookie" in response.headers["Vary"]

    def test_anonymous_template_without_visitor_state_is_public(self, client):
        response = client.get("/audience-template/")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=PLAIN_TEMPLATE,
            cache_control={"public", f"max-age={MAX_AGE}"},
        )
        assert "Cookie" in response.headers["Vary"]

    def test_rendered_csrf_token_keeps_the_response_private(self, client):
        response = client.get("/audience-csrf/")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=CSRF_TEMPLATE,
            cache_control={"private", f"max-age={MAX_AGE}"},
        )
        assert "Cookie" in response.headers["Vary"]

    def test_pending_message_keeps_the_response_private(self, client):
        response = client.get("/audience-flash/")

        assert_response(
            response,
            HTTPStatus.OK,
            messages=[(messages.INFO, "Saved.")],
            cache_control={"private", f"max-age={MAX_AGE}"},
        )

    def test_signed_in_visitor_gets_a_private_response(self, authenticated_client):
        response = authenticated_client.get("/audience-plain/")

        assert_response(
            response, HTTPStatus.OK, cache_control={"private", f"max-age={MAX_AGE}"}
        )
