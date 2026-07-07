from http import HTTPStatus

import pytest
from django.conf import settings
from django.contrib import messages
from django.test import Client
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
        assert "guidance" in context

    @staticmethod
    def test_guidance_is_stable_across_requests(rf):
        guidance = set()
        for _ in range(10):
            request = rf.get("/nonexistent-page/")
            guidance.add(str(custom_404(request, None).context_data["guidance"]))

        assert guidance == {
            "The page you're looking for doesn't exist or may have moved."
        }

    @staticmethod
    def test_themed_fields_are_present_alongside_guidance(rf):
        request = rf.get("/nonexistent-page/")
        response = custom_404(request, None)
        context = response.context_data

        assert str(context["guidance"]) == (
            "The page you're looking for doesn't exist or may have moved."
        )
        assert str(context["title"])
        assert str(context["message"])
        assert str(context["subtitle"])
        assert str(context["icon"])


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
        assert "guidance" in context
        assert "support_email" in context

    @staticmethod
    def test_guidance_is_stable_across_requests(rf):
        guidance = set()
        for _ in range(10):
            request = rf.get("/test/")
            guidance.add(str(custom_500(request).context_data["guidance"]))

        assert guidance == {"Something broke on our end. Try again in a moment."}

    @staticmethod
    def test_guidance_and_support_are_present(rf):
        request = rf.get("/test/")
        response = custom_500(request)
        context = response.context_data

        assert str(context["guidance"]) == (
            "Something broke on our end. Try again in a moment."
        )
        assert context["support_email"] == settings.SUPPORT_EMAIL
        assert str(context["title"])
        assert str(context["message"])
        assert str(context["subtitle"])
        assert str(context["icon"])

    @staticmethod
    def test_rendered_page_shows_guidance_and_support_mailto(rf):
        request = rf.get("/test/")

        content = custom_500(request).render().content.decode()

        assert "Something broke on our end. Try again in a moment." in content
        assert f"mailto:{settings.SUPPORT_EMAIL}" in content


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

    def test_missing_event_falls_back_to_events_list(self, client):
        response = client.get(self._event_url("no-such-event"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

    def test_junk_link_to_missing_event_falls_back_to_events_list(self, client):
        response = client.get(f"{self._event_url('ghost')}.")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

    def test_unpublished_event_redirects_like_a_missing_one(self, client, sphere):
        # Crucial: an unpublished event must produce the SAME response as a
        # missing one (302 to the events list with the same neutral message),
        # so a 404 never betrays whether an unannounced event with this slug
        # exists.
        unpublished = EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self._event_url(unpublished.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

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

    def test_head_request_is_recovered_like_get(self):
        # HEAD is a safe, idempotent navigation, so it is recovered exactly
        # like GET (302 to the events list) rather than dropped like POST. Each
        # method uses a fresh client so their unconsumed flash messages don't
        # pile up on top of each other.
        url = self._event_url("no-such-event")

        assert_response(
            Client().get(url),
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )
        assert_response(
            Client().head(url),
            HTTPStatus.FOUND,
            url=reverse("web:events"),
            messages=[(messages.INFO, "That event isn't available.")],
        )


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
