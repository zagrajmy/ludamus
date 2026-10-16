from http import HTTPStatus

import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.core.exceptions import ValidationError
from django.urls import reverse

from ludamus.links.db.django.models import Notification, Tag, TagCategory
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

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


@pytest.mark.django_db
class TestTagValidation:
    def test_parent_from_another_category_is_refused(self):
        genre = TagCategory.objects.create(name="Gatunek", slug="genre")
        horror = Tag.objects.create(category=genre, name="Horror", slug="horror")
        activity = TagCategory.objects.create(name="Gra", slug="activity")
        tag = Tag(category=activity, name="Mörk Borg", slug="mork-borg", parent=horror)

        with pytest.raises(ValidationError, match="parent's category"):
            tag.full_clean()

    def test_reparenting_under_own_descendant_is_refused(self):
        activity = TagCategory.objects.create(name="Gra", slug="activity")
        ttrpg = Tag.objects.create(category=activity, name="TTRPG", slug="ttrpg")
        ttrpg.parent = Tag.objects.create(
            category=activity, name="OSR", slug="osr", parent=ttrpg
        )

        with pytest.raises(ValidationError, match="own ancestor"):
            ttrpg.full_clean()
