from http import HTTPStatus

from django.urls import reverse

from ludamus.adapters.db.django.models import Notification
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _make_notification(recipient):
    return Notification.objects.create(
        recipient=recipient,
        kind=NotificationKind.WAITLIST_PROMOTED.value,
        title="A spot opened",
        body="You are in.",
        url="/x",
    )


class TestNavbarNotifications:
    def test_navbar_exposes_unread_count_for_recipient(
        self, authenticated_client, active_user
    ):
        _make_notification(active_user)

        response = authenticated_client.get(reverse("web:events"))

        assert response.context["navbar_notifications"].unread_count == 1
        assert response.context["navbar_notifications"].items[0].title == (
            "A spot opened"
        )

    def test_navbar_excludes_other_users_notifications(self, authenticated_client):
        other = UserFactory(username="someone-else", email="else@example.com")
        _make_notification(other)

        response = authenticated_client.get(reverse("web:events"))

        assert response.context["navbar_notifications"].unread_count == 0

    def test_mark_read_clears_unread(self, authenticated_client, active_user):
        notification = _make_notification(active_user)

        response = authenticated_client.post(
            reverse("web:notifications-mark-read"), {"next": "/"}
        )

        assert_response(response, HTTPStatus.FOUND, url="/")
        notification.refresh_from_db()
        assert notification.read_at is not None

    def test_mark_read_rejects_offsite_next(self, authenticated_client, active_user):
        _make_notification(active_user)

        response = authenticated_client.post(
            reverse("web:notifications-mark-read"),
            {"next": "https://evil.example.com/"},
        )

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
