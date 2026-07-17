from http import HTTPStatus

from django.contrib import messages
from django.contrib.sites.models import Site
from django.urls import reverse

from ludamus.links.db.django.models import Sphere
from tests.integration.utils import assert_response


class TestAuth0LogoutRedirectActionView:
    URL = reverse("web:crowd:auth0:logout-redirect")

    def test_ok_with_domain(self, client):
        domain = "example.com"
        site = Site.objects.create(domain=domain, name="Example")
        Sphere.objects.create(site=site, name="Example")
        response = client.get(self.URL, {"last_domain": domain, "redirect_to": "/test"})

        assert_response(response, HTTPStatus.FOUND, url="http://example.com/test")

    def test_ok_without_params(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_invalid_redirect_url_absolute(self, client):
        response = client.get(
            self.URL, {"redirect_to": "https://malicious.com/steal-data"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.WARNING, "Invalid redirect URL.")],
        )

    def test_invalid_redirect_url_protocol_relative(self, client):
        response = client.get(self.URL, {"redirect_to": "//malicious.com/steal-data"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.WARNING, "Invalid redirect URL.")],
        )

    def test_root_domain_redirect(self, client, settings):
        response = client.get(
            self.URL, {"last_domain": settings.ROOT_DOMAIN, "redirect_to": "/test-page"}
        )

        assert_response(
            response, HTTPStatus.FOUND, url=f"http://{settings.ROOT_DOMAIN}/test-page"
        )

    def test_subdomain_redirect(self, client, settings):
        subdomain = f"sub.{settings.ROOT_DOMAIN}"
        response = client.get(
            self.URL, {"last_domain": subdomain, "redirect_to": "/test-page"}
        )

        assert_response(response, HTTPStatus.FOUND, url=f"http://{subdomain}/test-page")

    def test_invalid_domain_for_redirect(self, client):
        response = client.get(
            self.URL, {"last_domain": "malicious.com", "redirect_to": "/test-page"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/test-page",
            messages=[(messages.WARNING, "Invalid domain for redirect.")],
        )

    def test_safe_relative_redirect_accepted(self, client):
        response = client.get(self.URL, {"redirect_to": "/dashboard"})

        assert_response(response, HTTPStatus.FOUND, url="/dashboard")

    def test_invalid_redirect_url_backslash(self, client):
        response = client.get(self.URL, {"redirect_to": "/\\evil.com"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.WARNING, "Invalid redirect URL.")],
        )

    def test_last_domain_fragment_bypass_rejected(self, client, settings):
        # `evil.com#x.<ROOT_DOMAIN>` satisfies a naive endswith() suffix match,
        # but a browser parses the host as evil.com. The hostname guard rejects
        # it before any suffix check runs.
        response = client.get(
            self.URL,
            {
                "last_domain": f"evil.com#x.{settings.ROOT_DOMAIN}",
                "redirect_to": "/test-page",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/test-page",
            messages=[(messages.WARNING, "Invalid domain for redirect.")],
        )
