import pytest
from django.urls import reverse


class TestSitesContext:
    @pytest.mark.usefixtures("panel_access_user")
    def test_manager_and_superuser_have_panel_access(self, authenticated_client):
        response = authenticated_client.get(reverse("web:events"))

        has_panel_access = response.context["has_panel_access"]
        assert has_panel_access is True

    def test_regular_user_has_no_panel_access(self, authenticated_client):
        response = authenticated_client.get(reverse("web:events"))

        has_panel_access = response.context["has_panel_access"]
        assert has_panel_access is False


class TestAnalyticsContext:
    def test_configured_key_exposes_posthog_config(self, client, settings):
        settings.POSTHOG_API_KEY = "phc_integration"
        settings.POSTHOG_HOST = "https://eu.i.posthog.com"

        response = client.get(reverse("web:events"))

        posthog_config = response.context["posthog_config"]
        assert posthog_config == {
            "api_key": "phc_integration",
            "host": "https://eu.i.posthog.com",
        }

    def test_unset_key_leaks_no_posthog_config(self, client, settings):
        settings.POSTHOG_API_KEY = ""

        response = client.get(reverse("web:events"))

        posthog_config = response.context["posthog_config"]
        assert posthog_config is None


class TestCurrentUserContext:
    def test_authenticated_render_exposes_current_user(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.get(reverse("web:events"))

        current_user = response.context["current_user"]
        info = response.context["current_user_info"]
        assert current_user.slug == active_user.slug
        assert info.pk == active_user.pk
        assert info.username == active_user.username

    def test_anonymous_render_has_no_current_user(self, client):
        response = client.get(reverse("web:events"))

        current_user = response.context["current_user"]
        assert current_user is None
        assert "current_user_info" not in response.context
