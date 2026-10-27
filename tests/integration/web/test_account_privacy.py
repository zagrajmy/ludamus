from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.core.management import call_command
from django.urls import reverse

from ludamus.links.db.django.models import Notification, SphereSubscription, User
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response


@pytest.mark.parametrize("age_band", ("unknown", "13_15"))
class TestRestrictedOptionalProcessing:
    def test_old_consent_cannot_expose_analytics_config(
        self, authenticated_client, active_user, settings, age_band
    ):
        settings.POSTHOG_API_KEY = "phc_privacy"
        User.objects.filter(pk=active_user.pk).update(age_band=age_band)

        response = authenticated_client.get(reverse("user:profile-privacy"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/user/privacy.html",
            context_data={"profile_active_tab": "privacy"},
        )
        analytics_config = response.context["posthog_config"]
        assert analytics_config is None

    def test_direct_subscription_request_is_refused(
        self, authenticated_client, active_user, non_root_sphere, age_band
    ):
        User.objects.filter(pk=active_user.pk).update(age_band=age_band)

        response = authenticated_client.post(
            reverse("web:sphere-subscribe", kwargs={"pk": non_root_sphere.pk})
        )

        assert_response(response, HTTPStatus.FORBIDDEN)
        assert not SphereSubscription.objects.filter(user=active_user).exists()

    def test_existing_subscription_sends_no_marketing(
        self,
        active_user,
        non_root_sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
        age_band,
    ):
        User.objects.filter(pk=active_user.pk).update(age_band=age_band)
        SphereSubscription.objects.create(user=active_user, sphere=non_root_sphere)
        start = datetime.now(UTC) + timedelta(days=3)
        EventFactory(
            sphere=non_root_sphere,
            start_time=start,
            end_time=start + timedelta(hours=3),
            publication_time=datetime.now(UTC) - timedelta(hours=1),
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("announce_published_events")

        assert mailoutbox == []
        assert not Notification.objects.filter(recipient=active_user).exists()


def test_signed_out_browser_has_no_tracking_configuration(client, settings):
    settings.POSTHOG_API_KEY = "phc_privacy"

    response = client.get(reverse("web:index"))

    analytics_config = response.context["posthog_config"]
    assert analytics_config is None
