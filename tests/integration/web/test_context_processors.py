from django.urls import reverse


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
