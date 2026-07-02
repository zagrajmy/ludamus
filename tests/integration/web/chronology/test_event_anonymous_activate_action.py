from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import User
from ludamus.pacts.crowd import UserType
from tests.integration.utils import assert_response


class TestEventAnonymousActivateActionView:
    URL = "web:chronology:event-anonymous-activate"

    def _get_url(self, event_slug: str) -> str:
        return reverse(self.URL, kwargs={"event_slug": event_slug})

    def test_get_authenticated_user(self, authenticated_client, event):
        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_get_event_doesnt_exist(self, client):
        response = client.get(self._get_url("nosuchevent"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("web:index"),
        )

    def test_get_no_enrollment_config(self, client, event):
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Anonymous enrollment is not available for this event.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_get_ok(self, client, enrollment_config, sphere):
        enrollment_config.allow_anonymous_enrollment = True
        enrollment_config.save()
        response = client.get(self._get_url(enrollment_config.event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:chronology:event", kwargs={"slug": enrollment_config.event.slug}
            ),
        )
        anonymous_user = User.objects.get()
        assert anonymous_user.username.startswith("anon_")
        assert anonymous_user.slug.startswith("code_")
        assert anonymous_user.user_type == UserType.ANONYMOUS
        assert not anonymous_user.is_active
        client.session["anonymous_user_code"] = anonymous_user.id
        client.session["anonymous_enrollment_active"] = True
        client.session["anonymous_event_id"] = enrollment_config.event.id
        client.session["anonymous_site_id"] = sphere.site.pk
