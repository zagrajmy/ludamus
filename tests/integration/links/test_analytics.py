from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest

from ludamus.links import analytics


@pytest.fixture(autouse=True)
def _reset_client():
    # Clear on setup only: tearing down after monkeypatch has restored the
    # real function is not guaranteed, and the next test clears it anyway.
    analytics.client.cache_clear()


class TestClient:
    def test_unset_key_builds_no_client(self, settings):
        settings.POSTHOG_API_KEY = ""

        assert analytics.client() is None

    def test_configured_key_builds_one_shared_client(self, settings, monkeypatch):
        settings.POSTHOG_API_KEY = "phc_integration"
        monkeypatch.setattr(analytics, "Posthog", MagicMock())

        assert analytics.client() is analytics.client()


class TestReportException:
    def test_unconfigured_builds_no_client_and_sends_nothing(
        self, settings, monkeypatch
    ):
        settings.POSTHOG_API_KEY = ""
        posthog_class = MagicMock()
        monkeypatch.setattr(analytics, "Posthog", posthog_class)

        request = HttpRequest()
        request.user = AnonymousUser()

        analytics.report_exception(ValueError("boom"), request)

        posthog_class.assert_not_called()

    def test_anonymous_request_reports_without_a_pk(self, monkeypatch):
        posthog = MagicMock()
        monkeypatch.setattr(analytics, "client", lambda: posthog)
        request = HttpRequest()
        request.path = "/events"
        request.user = AnonymousUser()

        analytics.report_exception(ValueError("boom"), request)

        _, kwargs = posthog.capture_exception.call_args
        assert kwargs["distinct_id"] == "anonymous"

    def test_authenticated_request_reports_the_pk(self, monkeypatch, active_user):
        posthog = MagicMock()
        monkeypatch.setattr(analytics, "client", lambda: posthog)
        request = HttpRequest()
        request.path = "/events"
        request.user = active_user

        analytics.report_exception(ValueError("boom"), request)

        _, kwargs = posthog.capture_exception.call_args
        assert kwargs["distinct_id"] == str(active_user.pk)

    def test_report_never_builds_a_person_profile(self, monkeypatch, active_user):
        # Consent lives in localStorage, unreadable here, so a fault report has
        # to stay safe to send for someone who declined.
        posthog = MagicMock()
        monkeypatch.setattr(analytics, "client", lambda: posthog)
        request = HttpRequest()
        request.path = "/events"
        request.user = active_user

        analytics.report_exception(ValueError("boom"), request)

        _, kwargs = posthog.capture_exception.call_args
        assert kwargs["properties"]["$process_person_profile"] is False
        assert kwargs["disable_geoip"] is True
