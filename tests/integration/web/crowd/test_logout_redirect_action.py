from http import HTTPStatus

import pytest
from django.contrib import messages
from django.contrib.sites.models import Site
from django.core import signing
from django.urls import reverse

from ludamus.links.db.django.models import Sphere
from tests.integration.utils import assert_response

INVALID_DOMAIN = [(messages.WARNING, "Invalid domain for redirect.")]


def _target(last_domain, *, salt="logout_target"):
    return signing.dumps({"last_domain": last_domain}, salt=salt)


class TestLogoutRedirectActionView:
    URL = reverse("web:crowd:auth:logout-redirect")

    @pytest.mark.parametrize(
        "domain", ("testserver", "sub.testserver"), ids=("root", "subdomain")
    )
    def test_lands_on_root_domain_family(self, client, domain):
        client.cookies["logout_target"] = _target(domain)

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=f"http://{domain}/")
        assert not response.cookies["logout_target"].value

    def test_lands_on_known_sphere_domain(self, client):
        site = Site.objects.create(domain="example.com", name="Example")
        Sphere.objects.create(site=site, name="Example")
        client.cookies["logout_target"] = _target("example.com")

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url="http://example.com/")

    @pytest.mark.parametrize(
        "domain",
        ("evil.com", "evil.com#x.testserver", "evil.com/x"),
        ids=("unknown", "fragment-bypass", "path"),
    )
    def test_refuses_foreign_domain(self, client, domain):
        client.cookies["logout_target"] = _target(domain)

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=INVALID_DOMAIN,
        )

    @pytest.mark.parametrize(
        "cookie",
        (
            _target("evil.com", salt="another-purpose"),
            "not-a-signed-value",
            signing.dumps({"elsewhere": "evil.com"}, salt="logout_target"),
        ),
        ids=("wrong-salt", "garbage", "wrong-shape"),
    )
    def test_ignores_unusable_cookie(self, client, cookie):
        client.cookies["logout_target"] = cookie

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_query_parameters_are_ignored(self, client):
        response = client.get(
            self.URL, {"last_domain": "evil.com", "redirect_to": "https://evil.com/"}
        )

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
