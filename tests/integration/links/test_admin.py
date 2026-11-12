import json
from http import HTTPStatus

import pytest
import requests
import responses
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from ludamus.links.db.django import admin as admin_module
from ludamus.links.db.django.models import Notification, ParleyReport, Tag, TagCategory
from ludamus.pacts.notifications import NotificationKind
from tests.integration.conftest import SphereFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.parley.helpers import configure_parley, decode_segment

CHANGELIST_URL = reverse("admin:db_main_user_changelist")


@pytest.fixture(name="superuser_client")
def superuser_client_fixture(client):
    client.force_login(
        UserFactory(username="adminuser", is_staff=True, is_superuser=True)
    )
    return client


@pytest.fixture(name="recipients")
def recipients_fixture():
    return [UserFactory(username="alice"), UserFactory(username="bob")]


def _action_post(recipients, **extra):
    return {
        "action": "send_notification",
        helpers.ACTION_CHECKBOX_NAME: [str(user.pk) for user in recipients],
        **extra,
    }


class TestSendNotificationAction:
    def test_first_pass_asks_for_the_message(self, superuser_client, recipients):
        response = superuser_client.post(CHANGELIST_URL, _action_post(recipients))

        assert_response(response, HTTPStatus.OK)
        assert not Notification.objects.exists()

    def test_apply_sends_one_notification_per_selected_user(
        self, superuser_client, recipients
    ):
        response = superuser_client.post(
            CHANGELIST_URL,
            _action_post(
                recipients,
                apply="Send",
                kind=NotificationKind.PRINTABLES_READY.value,
                title="Printables ready",
                body="Pick them up at the desk.",
                url="/events/",
            ),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=CHANGELIST_URL,
            messages=[(messages.INFO, "Notification sent to 2 user(s).")],
        )
        assert [
            (
                notification.recipient_id,
                notification.kind,
                notification.title,
                notification.body,
                notification.url,
            )
            for notification in Notification.objects.order_by("recipient_id")
        ] == [
            (
                user.pk,
                NotificationKind.PRINTABLES_READY.value,
                "Printables ready",
                "Pick them up at the desk.",
                "/events/",
            )
            for user in sorted(recipients, key=lambda user: user.pk)
        ]

    def test_apply_with_a_missing_title_sends_nothing(
        self, superuser_client, recipients
    ):
        response = superuser_client.post(
            CHANGELIST_URL,
            _action_post(
                recipients,
                apply="Send",
                kind=NotificationKind.PRINTABLES_READY.value,
                title="",
            ),
        )

        assert_response(response, HTTPStatus.OK)
        assert not Notification.objects.exists()


class TestTagAdmin:
    def test_add_sets_search_key(self, superuser_client):
        category = TagCategory.objects.create(name="Gra", slug="activity")

        response = superuser_client.post(
            reverse("admin:db_main_tag_add"),
            {"category": category.pk, "name": "Mörk Borg", "slug": "mork-borg"},
        )

        tag = Tag.objects.get(slug="mork-borg")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("admin:db_main_tag_changelist"),
            messages=[
                (
                    messages.SUCCESS,
                    (
                        f'The tag “<a href="/admin/db_main/tag/{tag.pk}/change/">'
                        "Mörk Borg</a>” was added successfully."
                    ),
                )
            ],
        )
        assert tag.search_key == "mork borg"


REPORTS_URL = reverse("admin:db_main_parleyreport_changelist")
WORKER_MODERATION_URL = "https://parley.example.com/moderation"
MODERATION_LIFETIME_SECONDS = 60


def _report(sphere, *, message_id):
    return ParleyReport.objects.create(
        sphere=sphere,
        reporter=UserFactory(),
        room_id=f"organizers:{sphere.pk}",
        message_id=message_id,
    )


def _delete_post(reports):
    return {
        "action": "delete_reported_messages",
        helpers.ACTION_CHECKBOX_NAME: [str(report.pk) for report in reports],
    }


class TestDeleteReportedMessagesAction:
    def test_staff_delete_resolves_every_report_of_the_message(
        self, superuser_client, settings
    ):
        configure_parley(settings)
        sphere = SphereFactory()
        report = _report(sphere, message_id=7)
        same_message = _report(sphere, message_id=7)
        _report(sphere, message_id=8)

        with responses.RequestsMock() as worker:
            worker.post(WORKER_MODERATION_URL, status=204)
            response = superuser_client.post(REPORTS_URL, _delete_post([report]))
            [call] = worker.calls

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[(messages.INFO, "Deleted 1 message(s).")],
        )
        claims = decode_segment(json.loads(call.request.body)["token"].split(".")[1])
        assert (claims["aud"], claims["room"], claims["message"]) == (
            "parley-moderation",
            f"organizers:{sphere.pk}",
            7,
        )
        assert claims["exp"] - claims["iat"] == MODERATION_LIFETIME_SECONDS
        assert set(
            ParleyReport.objects.filter(resolved_at__isnull=False).values_list(
                "pk", flat=True
            )
        ) == {report.pk, same_message.pk}

    def test_a_message_the_room_no_longer_has_counts_as_deleted(
        self, superuser_client, settings
    ):
        configure_parley(settings)
        report = _report(SphereFactory(), message_id=7)

        with responses.RequestsMock() as worker:
            worker.post(WORKER_MODERATION_URL, status=404)
            superuser_client.post(REPORTS_URL, _delete_post([report]))

        report.refresh_from_db()
        assert report.resolved_at is not None

    @pytest.mark.parametrize(
        "answer",
        ({"status": 503}, {"body": requests.ConnectionError()}),
        ids=["error", "unreachable"],
    )
    def test_a_worker_that_does_not_answer_leaves_the_report_open(
        self, superuser_client, settings, answer
    ):
        configure_parley(settings)
        report = _report(SphereFactory(), message_id=7)

        with responses.RequestsMock() as worker:
            worker.post(WORKER_MODERATION_URL, **answer)
            response = superuser_client.post(REPORTS_URL, _delete_post([report]))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (messages.INFO, "Deleted 0 message(s)."),
                (
                    messages.ERROR,
                    "1 could not be deleted: the chat Worker did not answer.",
                ),
            ],
        )
        report.refresh_from_db()
        assert report.resolved_at is None

    def test_without_a_worker_nothing_is_deleted(self, superuser_client):
        report = _report(SphereFactory(), message_id=7)

        response = superuser_client.post(REPORTS_URL, _delete_post([report]))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (messages.INFO, "Deleted 0 message(s)."),
                (
                    messages.ERROR,
                    "1 could not be deleted: the chat Worker did not answer.",
                ),
            ],
        )
        report.refresh_from_db()
        assert report.resolved_at is None

    def test_an_admin_started_without_services_says_so(
        self, superuser_client, monkeypatch
    ):
        monkeypatch.setattr(admin_module._wiring, "services", None)
        report = _report(SphereFactory(), message_id=7)

        with pytest.raises(ImproperlyConfigured):
            superuser_client.post(REPORTS_URL, _delete_post([report]))

    def test_staff_who_may_only_view_reports_cannot_delete(self, client, settings):
        configure_parley(settings)
        viewer = UserFactory(is_staff=True)
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_parleyreport")
        )
        client.force_login(viewer)
        report = _report(SphereFactory(), message_id=7)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as worker:
            worker.post(WORKER_MODERATION_URL, status=204)
            client.post(REPORTS_URL, _delete_post([report]))
            assert not worker.calls

        report.refresh_from_db()
        assert report.resolved_at is None
