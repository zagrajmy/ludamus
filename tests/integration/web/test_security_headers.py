import re
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.adapters.web.django.views import EventsPageView
from ludamus.edges.settings import CSP_POLICY
from ludamus.pacts.event import LandingStatsDTO
from tests.integration.utils import assert_response

REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
ENFORCE_HEADER = "Content-Security-Policy"


def _directive(*, header: str, name: str) -> str:
    match = re.search(rf"(?:^|; ){re.escape(name)} ([^;]*)", header)
    assert match, f"{name!r} directive not found in header: {header!r}"
    return match.group(1)


def _assert_body_nonce_matches_header(response) -> None:
    script_src = _directive(header=response.headers[ENFORCE_HEADER], name="script-src")
    assert "'unsafe-inline'" not in script_src
    match = re.search(r"'nonce-([^']+)'", script_src)
    assert match, f"no nonce token in script-src: {script_src!r}"
    body_nonces = set(re.findall(r'nonce="([^"]+)"', response.content.decode()))
    assert body_nonces == {match.group(1)}


@pytest.fixture(name="enforced_header")
def enforced_header_fixture(client, settings, non_root_sphere) -> str:
    # The middleware stamps every response, so the sphere-domain index
    # redirect is the simplest surface to assert headers on without
    # replicating a rendered page's full context.
    settings.SECURE_CSP = CSP_POLICY

    response = client.get(reverse("web:index"), HTTP_HOST=non_root_sphere.site.domain)

    assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))
    assert REPORT_ONLY_HEADER not in response.headers
    return response.headers[ENFORCE_HEADER]


class TestCSPEnforceHeader:
    def test_header_sent_when_production_policy_active(self, enforced_header):
        assert "default-src 'self'" in enforced_header
        assert "unsafe-eval" not in enforced_header
        assert "img-src 'self' data: blob: https:" in enforced_header
        assert "frame-ancestors 'none'" in enforced_header

    def test_style_src_keeps_unsafe_inline(self, enforced_header):
        assert "'unsafe-inline'" in _directive(header=enforced_header, name="style-src")

    def test_script_src_has_no_unsafe_inline(self, enforced_header):
        # No inline script rendered on this redirect (no nonce read yet), so
        # the CSP.NONCE sentinel is dropped rather than substituted — see
        # test_nonce_in_header_matches_nonce_rendered_in_page for the
        # nonce-carrying case. Either way, 'unsafe-inline' must never appear.
        assert "'unsafe-inline'" not in _directive(
            header=enforced_header, name="script-src"
        )

    def test_no_csp_headers_by_default(self, client, non_root_sphere):
        response = client.get(
            reverse("web:index"), HTTP_HOST=non_root_sphere.site.domain
        )

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))
        assert REPORT_ONLY_HEADER not in response.headers
        assert ENFORCE_HEADER not in response.headers


class TestCSPNonce:
    # web:events actually renders base.html (unlike the index redirect), so
    # its first inline script (the FOUC-prevention script) forces the CSP
    # nonce to materialize.
    URL = reverse("web:events")

    def test_nonce_in_header_matches_nonce_rendered_in_page(self, client, settings):
        settings.SECURE_CSP = CSP_POLICY

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "announcements": [],
                "past_events": [],
                "upcoming_events": [],
                "view": ANY,
            },
            template_name=["index.html"],
        )
        _assert_body_nonce_matches_header(response)

    def test_landing_page_nonce_matches_the_header(self, client, settings):
        settings.SECURE_CSP = CSP_POLICY

        response = client.get(reverse("web:index"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"stats": LandingStatsDTO(events=0, sessions=0)},
            template_name=["landing_page.html"],
        )
        _assert_body_nonce_matches_header(response)


class TestCSP500PageNonce:
    # 500_dynamic.html doesn't extend base.html (it must stay self-contained
    # so it still renders if something upstream broke), so it's a separate
    # edge case from TestCSPNonce: it's rendered via a deferred
    # TemplateResponse from Django's exception-handling path, not a plain
    # view return, and it must independently prove it gets a nonce that
    # matches the header under the real middleware chain — not just via
    # calling custom_500() directly the way test_error_views.py does.
    def test_500_page_gets_a_nonce_matching_the_header(
        self, client, settings, monkeypatch
    ):
        settings.SECURE_CSP = CSP_POLICY
        settings.DEBUG = False

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(EventsPageView, "get", _boom)
        # custom_500 picks a themed error message at random; pin it so the
        # rendered context below is an exact, assertable value like every
        # other assert_response call, rather than glossing over it wholesale.
        monkeypatch.setattr("secrets.randbelow", lambda _n: 0)
        client.raise_request_exception = False

        response = client.get(reverse("web:events"))

        assert_response(
            response,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            context_data={
                "error_code": HTTPStatus.INTERNAL_SERVER_ERROR,
                "title": "Total Server Kill!",
                "message": "Everyone needs to roll new characters",
                "subtitle": "The server party has been wiped. Respawning soon...",
                "icon": "heartbreak",
                "guidance": "Our best people are on it.",
                "support_email": settings.SUPPORT_EMAIL,
            },
            template_name="500_dynamic.html",
        )
        _assert_body_nonce_matches_header(response)
