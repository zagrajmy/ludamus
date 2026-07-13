from http import HTTPStatus

from django.urls import reverse

from ludamus.edges.settings import CSP_REPORT_ONLY_POLICY
from tests.integration.utils import assert_response

REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
ENFORCE_HEADER = "Content-Security-Policy"


class TestCSPReportOnlyHeader:
    # The middleware stamps every response, so the index redirect is the
    # simplest surface to assert headers on without replicating a rendered
    # page's full context.
    URL = reverse("web:index")

    def test_header_sent_when_production_policy_active(self, client, settings):
        settings.SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))
        header = response.headers[REPORT_ONLY_HEADER]
        assert "default-src 'self'" in header
        assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in header
        assert "img-src 'self' data: https:" in header
        assert "frame-ancestors 'none'" in header
        assert ENFORCE_HEADER not in response.headers

    def test_no_csp_headers_by_default(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))
        assert REPORT_ONLY_HEADER not in response.headers
        assert ENFORCE_HEADER not in response.headers
