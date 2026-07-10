from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from ludamus.edges.settings import CSP_REPORT_ONLY_POLICY
from tests.integration.utils import assert_response

REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
ENFORCE_HEADER = "Content-Security-Policy"

EVENTS_CONTEXT = {
    "announcements": [],
    "past_events": [],
    "upcoming_events": [],
    "view": ANY,
}


class TestCSPReportOnlyHeader:
    URL = reverse("web:events")

    def test_header_sent_when_production_policy_active(self, client, settings):
        settings.SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EVENTS_CONTEXT,
            template_name=["index.html"],
        )
        header = response.headers[REPORT_ONLY_HEADER]
        assert "default-src 'self'" in header
        assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in header
        assert "img-src 'self' data: https:" in header
        assert "frame-ancestors 'none'" in header
        assert ENFORCE_HEADER not in response

    def test_no_csp_headers_by_default(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=EVENTS_CONTEXT,
            template_name=["index.html"],
        )
        assert REPORT_ONLY_HEADER not in response
        assert ENFORCE_HEADER not in response
