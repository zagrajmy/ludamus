from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import EventBan
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestBansPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:bans", kwargs={"slug": event.slug})

    def test_anonymous_redirected_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_non_manager_redirected(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_manager_gets_page(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self._url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context["active_nav"] == "bans"

    def test_manager_bans_by_username(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        troublemaker = UserFactory(username="tm", email="tm@example.com", name="TM")

        response = authenticated_client.post(
            self._url(event), data={"identifier": "tm", "reason": "incites violence"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "User banned from the event.")],
            url=self._url(event),
        )
        ban = EventBan.objects.get(event=event, user=troublemaker)
        assert ban.reason == "incites violence"

    def test_ban_unknown_identifier_reports_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self._url(event), data={"identifier": "ghost"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "No user found with that username or email.")],
            url=self._url(event),
        )
        assert not EventBan.objects.exists()

    def test_manager_removes_ban(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        troublemaker = UserFactory(username="tm2", email="tm2@example.com", name="TM2")
        ban = EventBan.objects.create(event=event, user=troublemaker)

        response = authenticated_client.post(
            reverse("panel:ban-delete", kwargs={"slug": event.slug, "pk": ban.pk})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Ban removed.")],
            url=self._url(event),
        )
        assert not EventBan.objects.filter(pk=ban.pk).exists()
