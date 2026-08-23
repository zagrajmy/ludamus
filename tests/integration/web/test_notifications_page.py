from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import Notification
from ludamus.pacts.enrollment import NotificationDTO
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import UserFactory
from tests.integration.utils import (
    PageMatcher,
    assert_login_required,
    assert_response,
    assert_response_404,
)

_PAGE_SIZES = [10, 20, 50, 100]


def _make_notification(recipient, *, url="/somewhere", title="A spot opened"):
    return Notification.objects.create(
        recipient=recipient,
        kind=NotificationKind.WAITLIST_PROMOTED.value,
        title=title,
        body="You are in.",
        url=url,
    )


def _dto(notification):
    notification.refresh_from_db()
    return NotificationDTO.model_validate(notification)


class TestNotificationsPageView:
    @staticmethod
    def _url():
        return reverse("web:notifications")

    def test_anonymous_redirected_to_login(self, client):
        response = client.get(self._url())

        assert_login_required(response, self._url())

    def test_empty_history_renders_empty_state(self, authenticated_client):
        response = authenticated_client.get(self._url())

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="notifications/index.html",
            context_data={
                "notifications": [],
                "active_nav": "notifications",
                "page_obj": PageMatcher(number=1, num_pages=1),
                "page_sizes": _PAGE_SIZES,
            },
        )

    def test_lists_recipient_notifications_newest_first(
        self, authenticated_client, active_user
    ):
        older = _make_notification(active_user, title="Older")
        newer = _make_notification(active_user, title="Newer")

        response = authenticated_client.get(self._url())

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="notifications/index.html",
            context_data={
                "notifications": [_dto(newer), _dto(older)],
                "active_nav": "notifications",
                "page_obj": PageMatcher(number=1, num_pages=1),
                "page_sizes": _PAGE_SIZES,
            },
        )

    def test_excludes_other_users_notifications(self, authenticated_client):
        other = UserFactory(username="someone-else", email="else@example.com")
        _make_notification(other)

        response = authenticated_client.get(self._url())

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="notifications/index.html",
            context_data={
                "notifications": [],
                "active_nav": "notifications",
                "page_obj": PageMatcher(number=1, num_pages=1),
                "page_sizes": _PAGE_SIZES,
            },
        )


class TestNotificationOpenView:
    @staticmethod
    def _url(pk):
        return reverse("web:notification-open", kwargs={"pk": pk})

    def test_anonymous_redirected_to_login(self, client, active_user):
        notification = _make_notification(active_user)

        response = client.get(self._url(notification.pk))

        assert_login_required(response, self._url(notification.pk))

    def test_destination_notification_marks_read_and_forwards(
        self, authenticated_client, active_user
    ):
        notification = _make_notification(active_user, url="/target")

        response = authenticated_client.get(self._url(notification.pk))

        assert_response(response, HTTPStatus.FOUND, url="/target")
        notification.refresh_from_db()
        assert notification.read_at is not None

    def test_content_notification_marks_read_and_lands_on_list(
        self, authenticated_client, active_user
    ):
        notification = _make_notification(active_user, url="")

        response = authenticated_client.get(self._url(notification.pk))

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:notifications"))
        notification.refresh_from_db()
        assert notification.read_at is not None

    def test_foreign_notification_is_not_found_and_unchanged(
        self, authenticated_client
    ):
        other = UserFactory(username="someone-else", email="else@example.com")
        notification = _make_notification(other)

        response = authenticated_client.get(self._url(notification.pk))

        assert_response_404(response)
        notification.refresh_from_db()
        assert notification.read_at is None


class TestNotificationModalComponentView:
    @staticmethod
    def _url(pk):
        return reverse("web:notification-modal", kwargs={"pk": pk})

    def test_anonymous_redirected_to_login(self, client, active_user):
        notification = _make_notification(active_user, url="")

        response = client.get(self._url(notification.pk))

        assert_login_required(response, self._url(notification.pk))

    def test_renders_dialog_and_marks_read(self, authenticated_client, active_user):
        notification = _make_notification(active_user, url="", title="Big news")

        response = authenticated_client.get(self._url(notification.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="notifications/parts/modal.html",
            context_data={"notification": _dto(notification)},
        )

    def test_foreign_notification_is_not_found(self, authenticated_client):
        other = UserFactory(username="someone-else", email="else@example.com")
        notification = _make_notification(other, url="")

        response = authenticated_client.get(self._url(notification.pk))

        assert_response_404(response)
