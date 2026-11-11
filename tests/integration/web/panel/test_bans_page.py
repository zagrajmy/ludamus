import base64
import json
from http import HTTPStatus

import pytest
import responses
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import EventBan
from ludamus.pacts.safety import EventBanDTO
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)
from tests.integration.web.parley.helpers import configure_parley, decode_segment


@pytest.mark.django_db
class TestBansPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:bans", kwargs={"slug": event.slug})

    def test_anonymous_redirected_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_non_manager_redirected(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_not_a_manager(response)

    def test_manager_gets_page(self, panel_client, event):
        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/bans.html",
            context_data={**panel_context(event, active_nav="bans"), "bans": []},
        )

    def test_page_lists_existing_bans(self, panel_client, event):
        tm = UserFactory(username="tm0", email="tm0@example.com", name="Banned Bob")
        reasoned = EventBan.objects.create(
            event=event, user=tm, reason="incites violence"
        )
        # A reasonless ban reaches the template with an empty reason, which the
        # bans table renders as the "—" fallback column.
        nr = UserFactory(username="nr0", email="nr0@example.com", name="No Reason")
        reasonless = EventBan.objects.create(event=event, user=nr, reason="")

        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/bans.html",
            context_data={
                **panel_context(event, active_nav="bans"),
                "bans": [
                    EventBanDTO(
                        pk=reasoned.pk,
                        user_name="Banned Bob",
                        user_slug=tm.slug,
                        reason="incites violence",
                        created_at=reasoned.created_at,
                    ),
                    EventBanDTO(
                        pk=reasonless.pk,
                        user_name="No Reason",
                        user_slug=nr.slug,
                        reason="",
                        created_at=reasonless.created_at,
                    ),
                ],
            },
        )

    def test_get_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:bans", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_post_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:bans", kwargs={"slug": "nonexistent"})

        response = panel_client.post(url, data={"identifier": "x"})

        assert_event_not_found(response)

    def test_delete_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:ban-delete", kwargs={"slug": "nonexistent", "pk": 1})

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_post_blank_identifier_reports_error(self, panel_client, event):
        response = panel_client.post(self._url(event), data={"identifier": "  "})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "No user found with that username or email.")],
            url=self._url(event),
        )
        assert not EventBan.objects.exists()

    def test_manager_bans_by_username(self, panel_client, event):
        troublemaker = UserFactory(username="tm", email="tm@example.com", name="TM")

        response = panel_client.post(
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

    def test_ban_takes_back_the_chat_pass_once_committed(
        self, panel_client, event, settings, django_capture_on_commit_callbacks
    ):
        public_key = configure_parley(settings)
        troublemaker = UserFactory(username="tm", email="tm@example.com", name="TM")

        with responses.RequestsMock() as worker:
            worker.post("https://parley.example.com/revoke", status=204)
            with django_capture_on_commit_callbacks(execute=True):
                panel_client.post(self._url(event), data={"identifier": "tm"})

            [call] = worker.calls
        token = json.loads(call.request.body)["token"]
        header, body, signature = token.split(".")
        claims = decode_segment(body)
        assert claims["aud"] == "parley-revocation"
        assert claims["sphere"] == str(event.sphere_id)
        assert claims["sub"] == str(troublemaker.pk)
        assert claims["revokedBefore"] == claims["iat"]
        assert claims["exp"] == claims["iat"] + 12 * 3600
        public_key.verify(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
            f"{header}.{body}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def test_ban_stands_when_the_chat_worker_is_down(
        self, panel_client, event, settings, django_capture_on_commit_callbacks
    ):
        configure_parley(settings)
        troublemaker = UserFactory(username="tm", email="tm@example.com", name="TM")

        with responses.RequestsMock() as worker:
            worker.post("https://parley.example.com/revoke", status=503)
            with django_capture_on_commit_callbacks(execute=True):
                response = panel_client.post(
                    self._url(event), data={"identifier": "tm"}
                )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "User banned from the event.")],
            url=self._url(event),
        )
        assert EventBan.objects.filter(event=event, user=troublemaker).exists()

    def test_ban_unknown_identifier_reports_error(self, panel_client, event):
        response = panel_client.post(self._url(event), data={"identifier": "ghost"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "No user found with that username or email.")],
            url=self._url(event),
        )
        assert not EventBan.objects.exists()

    def test_manager_removes_ban(self, panel_client, event):
        troublemaker = UserFactory(username="tm2", email="tm2@example.com", name="TM2")
        ban = EventBan.objects.create(event=event, user=troublemaker)

        response = panel_client.post(
            reverse("panel:ban-delete", kwargs={"slug": event.slug, "pk": ban.pk})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Ban removed.")],
            url=self._url(event),
        )
        assert not EventBan.objects.filter(pk=ban.pk).exists()

    def test_manager_cannot_remove_ban_from_other_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        troublemaker = UserFactory(username="tm3", email="tm3@example.com", name="TM3")
        foreign_ban = EventBan.objects.create(event=other_event, user=troublemaker)

        response = panel_client.post(
            reverse(
                "panel:ban-delete", kwargs={"slug": event.slug, "pk": foreign_ban.pk}
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Ban removed.")],
            url=self._url(event),
        )
        assert EventBan.objects.filter(pk=foreign_ban.pk).exists()
