from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
)
from tests.integration.utils import assert_response


class TestAnonymousLoadActionView:
    URL = reverse("web:chronology:anonymous-load")

    def test_authenticated_user(self, authenticated_client):
        response = authenticated_client.post(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_no_code(self, client):
        response = client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Please enter a code.")],
            url=reverse("web:index"),
        )

    def test_no_code_referer(self, client, event):
        event_url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        response = client.post(self.URL, HTTP_REFERER=event_url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Please enter a code.")],
            url=event_url,
        )

    def test_user_does_not_exist(self, client):
        response = client.post(self.URL, data={"code": "c1234"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid code. Please check and try again.")],
            url=reverse("web:index"),
        )

    def test_user_does_not_exist_referer(self, client, event):
        event_url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        response = client.post(self.URL, data={"code": "c1234"}, HTTP_REFERER=event_url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid code. Please check and try again.")],
            url=event_url,
        )

    def test_no_enrollments(self, client, anonymous_user_factory):
        anonymous_user_factory(slug="code_c1234")
        response = client.post(self.URL, data={"code": "c1234"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No enrollments found for this code.")],
            url=reverse("web:index"),
        )

    def test_ok(self, client, anonymous_user_factory, agenda_item):
        user = anonymous_user_factory(slug="code_c1234")
        SessionParticipation.objects.create(
            user=user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        response = client.post(self.URL, data={"code": "c1234"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Code loaded successfully. You can now manage your enrollments.",
                )
            ],
            url=reverse(
                "web:chronology:event", kwargs={"slug": agenda_item.space.event.slug}
            ),
        )
        assert client.session["anonymous_user_code"] == user.slug.split("_")[1]
        assert client.session["anonymous_enrollment_active"]
        assert client.session["anonymous_event_id"] == agenda_item.space.event.id
        assert (
            client.session["anonymous_site_id"]
            == agenda_item.space.event.sphere.site_id
        )
