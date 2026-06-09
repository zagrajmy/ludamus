from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.web.django.error_views import custom_404, custom_500
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response, assert_response_404


@pytest.mark.django_db
class TestCustom404:

    @staticmethod
    def test_returns_404_status_code(rf):
        request = rf.get("/nonexistent-page/")
        response = custom_404(request, None)
        assert response.status_code == HTTPStatus.NOT_FOUND

    @staticmethod
    def test_uses_404_dynamic_template(rf):
        request = rf.get("/nonexistent-page/")
        response = custom_404(request, None)
        assert response.template_name == "404_dynamic.html"
        assert response.status_code == HTTPStatus.NOT_FOUND

    @staticmethod
    def test_context_contains_required_fields(rf):
        request = rf.get("/nonexistent-page/")
        response = custom_404(request, None)
        context = response.context_data

        assert "error_code" in context
        assert context["error_code"] == HTTPStatus.NOT_FOUND
        assert "title" in context
        assert "message" in context
        assert "subtitle" in context
        assert "icon" in context

    @staticmethod
    def test_selects_random_message(rf):
        responses = []
        for _ in range(10):
            request = rf.get("/nonexistent-page/")
            response = custom_404(request, None)
            context = response.context_data
            responses.append(context["title"])

        unique_responses = set(responses)
        assert len(unique_responses) > 1 or len(responses) == 1

    @staticmethod
    def test_message_structure_validity(rf):
        request = rf.get("/nonexistent-page/")
        response = custom_404(request, None)
        context = response.context_data

        assert isinstance(context["title"], str)
        assert context["title"]
        assert isinstance(context["message"], str)
        assert context["message"]
        assert isinstance(context["subtitle"], str)
        assert context["subtitle"]
        assert isinstance(context["icon"], str)
        assert context["icon"]


@pytest.mark.django_db
class TestCustom500:
    @staticmethod
    def test_returns_500_status_code(rf):
        request = rf.get("/test/")
        response = custom_500(request)
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @staticmethod
    def test_uses_500_dynamic_template(rf):
        request = rf.get("/test/")
        response = custom_500(request)
        assert response.template_name == "500_dynamic.html"
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @staticmethod
    def test_context_contains_required_fields(rf):
        request = rf.get("/test/")
        response = custom_500(request)
        context = response.context_data

        assert "error_code" in context
        assert context["error_code"] == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "title" in context
        assert "message" in context
        assert "subtitle" in context
        assert "icon" in context

    @staticmethod
    def test_selects_random_message(rf):
        responses = []
        for _ in range(10):
            request = rf.get("/test/")
            response = custom_500(request)
            context = response.context_data
            responses.append(context["title"])

        unique_responses = set(responses)
        assert len(unique_responses) > 1 or len(responses) == 1

    @staticmethod
    def test_message_structure_validity(rf):
        request = rf.get("/test/")
        response = custom_500(request)
        context = response.context_data

        assert isinstance(context["title"], str)
        assert context["title"]
        assert isinstance(context["message"], str)
        assert context["message"]
        assert isinstance(context["subtitle"], str)
        assert context["subtitle"]
        assert isinstance(context["icon"], str)
        assert context["icon"]


@pytest.mark.django_db
class TestSemantic404Recovery:
    @staticmethod
    def _event_url(slug: str) -> str:
        return reverse("web:chronology:event", kwargs={"slug": slug})

    def test_trailing_dot_redirects_to_canonical_event(self, client, event):
        response = client.get(f"{self._event_url(event.slug)}.")

        assert_response(
            response, HTTPStatus.MOVED_PERMANENTLY, url=self._event_url(event.slug)
        )

    def test_trailing_emoji_redirects_to_canonical_event(self, client, event):
        response = client.get(f"{self._event_url(event.slug)}\U0001f600")

        assert_response(
            response, HTTPStatus.MOVED_PERMANENTLY, url=self._event_url(event.slug)
        )

    def test_missing_event_falls_back_to_sphere_home(self, client):
        response = client.get(self._event_url("no-such-event"))

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_junk_link_to_missing_event_falls_back_to_sphere_home(self, client):
        response = client.get(f"{self._event_url('ghost')}.")

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_unpublished_event_redirects_like_a_missing_one(self, client, sphere):
        # Crucial: an unpublished event must produce the SAME response as a
        # missing one (302 to home), so a 404 never betrays whether an
        # unannounced event with this slug exists.
        unpublished = EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self._event_url(unpublished.slug))

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_non_event_path_keeps_themed_404(self, client):
        # A resolvable, non-event path that 404s (a missing flatpage) must not
        # be swept up by the event fallback.
        response = client.get("/page/no-such-flatpage/")

        assert_response_404(response)

    def test_fully_unresolvable_path_renders_themed_404(self, client):
        # No URL pattern matches, so request.resolver_match is None; the themed
        # 404 (and its navbar) must still render.
        response = client.get("/totally/unknown/place/")

        assert_response_404(response)

    @staticmethod
    def test_non_get_request_falls_through_to_themed_404(rf):
        # Only safe, idempotent navigations are recovered; a 404'd POST keeps
        # the themed page rather than being redirected.
        response = custom_404(rf.post("/chronology/event/ghost./"), None)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.template_name == "404_dynamic.html"

    def test_head_request_is_recovered_like_get(self, client):
        # HEAD is a safe, idempotent navigation, so it is recovered exactly
        # like GET (302 to the sphere home) rather than dropped like POST.
        url = self._event_url("no-such-event")

        assert_response(client.get(url), HTTPStatus.FOUND, url=reverse("web:index"))
        assert_response(client.head(url), HTTPStatus.FOUND, url=reverse("web:index"))


@pytest.mark.django_db
class TestErrorViewsIntegration:
    @staticmethod
    def test_404_and_500_have_different_error_codes(rf):
        request = rf.get("/test/")

        response_404 = custom_404(request, None)
        response_500 = custom_500(request)

        assert response_404.context_data["error_code"] == HTTPStatus.NOT_FOUND
        assert (
            response_500.context_data["error_code"] == HTTPStatus.INTERNAL_SERVER_ERROR
        )
        assert response_404.status_code == HTTPStatus.NOT_FOUND
        assert response_500.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
