from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.inits.builders import build_announcement_fanout
from ludamus.links.db.django.models import (
    Announcement,
    Notification,
    NotificationSubscription,
)
from ludamus.pacts.multiverse import AnnouncementDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.multiverse.helpers import (
    assert_not_a_sphere_manager,
    sphere_settings_context,
)

ANNOUNCEMENTS_PANEL_CONTEXT = sphere_settings_context(active_tab="announcements")


class TestAnnouncementsPageView:
    url = reverse("multiverse:panel:announcements")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_login_required(response, self.url)

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_not_a_sphere_manager(response)

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/list.html",
            context_data={**ANNOUNCEMENTS_PANEL_CONTEXT, "announcements": []},
        )

    def test_get_returns_announcements_scoped_to_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="Mine", content="body"
        )
        Announcement.objects.create(
            sphere=non_root_sphere, title="Other", content="body"
        )

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/list.html",
            context_data={
                **ANNOUNCEMENTS_PANEL_CONTEXT,
                "announcements": [AnnouncementDTO.model_validate(announcement)],
            },
        )

    def test_get_includes_drafts(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        Announcement.objects.create(
            sphere=sphere, title="Draft", content="b", is_published=False
        )

        response = authenticated_client.get(self.url)

        names = [a.title for a in response.context["announcements"]]
        assert names == ["Draft"]


class TestAnnouncementCreatePageView:
    url = reverse("multiverse:panel:announcement-create")

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_not_a_sphere_manager(response)

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/create.html",
            context_data={**ANNOUNCEMENTS_PANEL_CONTEXT, "form": ANY},
            not_contains='aria-describedby="id_title_errors"',
        )

    def test_post_rerenders_form_on_invalid_data(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data={"title": "", "content": ""}
        )

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/create.html",
            context_data={**ANNOUNCEMENTS_PANEL_CONTEXT, "form": ANY},
            contains=['aria-describedby="id_title_errors"', 'id="id_title_errors"'],
        )
        assert not Announcement.objects.filter(sphere=sphere).exists()

    def test_post_creates_published_announcement(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data={"title": "Hello", "content": "Body", "is_published": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement created successfully.")],
            url="/multiverse/panel/announcements/",
        )
        announcement = Announcement.objects.get(sphere=sphere)
        assert announcement.title == "Hello"
        assert announcement.content == "Body"
        assert announcement.is_published is True

    def test_post_creates_draft_when_unchecked(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        authenticated_client.post(self.url, data={"title": "Hello", "content": "Body"})

        announcement = Announcement.objects.get(sphere=sphere)
        assert announcement.is_published is False


class TestAnnouncementEditPageView:
    @staticmethod
    def get_url(announcement):
        return reverse(
            "multiverse:panel:announcement-edit", kwargs={"pk": announcement.pk}
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="T", content="C"
        )

        response = authenticated_client.get(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/edit.html",
            context_data={
                **ANNOUNCEMENTS_PANEL_CONTEXT,
                "form": ANY,
                "announcement": AnnouncementDTO.model_validate(announcement),
            },
        )

    def test_get_redirects_when_announcement_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="T", content="C"
        )

        response = authenticated_client.get(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Announcement not found.")],
            url="/multiverse/panel/announcements/",
        )

    def test_post_updates_announcement(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="Old", content="Old", is_published=True
        )

        response = authenticated_client.post(
            self.get_url(announcement), data={"title": "New", "content": "New body"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement updated successfully.")],
            url="/multiverse/panel/announcements/",
        )
        announcement.refresh_from_db()
        assert announcement.title == "New"
        assert announcement.content == "New body"
        assert announcement.is_published is False

    def test_post_rerenders_form_on_invalid_data(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="Original", content="C"
        )

        response = authenticated_client.post(
            self.get_url(announcement), data={"title": "", "content": ""}
        )

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/edit.html",
            context_data={
                **ANNOUNCEMENTS_PANEL_CONTEXT,
                "form": ANY,
                "announcement": AnnouncementDTO.model_validate(announcement),
            },
        )
        announcement.refresh_from_db()
        assert announcement.title == "Original"

    def test_post_redirects_when_announcement_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="Other", content="C"
        )

        response = authenticated_client.post(
            self.get_url(announcement), data={"title": "New", "content": "New body"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Announcement not found.")],
            url="/multiverse/panel/announcements/",
        )
        announcement.refresh_from_db()
        assert announcement.title == "Other"


class TestAnnouncementDeletePageView:
    @staticmethod
    def get_url(announcement):
        return reverse(
            "multiverse:panel:announcement-delete", kwargs={"pk": announcement.pk}
        )

    def test_get_renders_confirm_page_for_sphere_manager(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="To delete", content="C"
        )

        response = authenticated_client.get(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/announcements/delete.html",
            context_data={
                **ANNOUNCEMENTS_PANEL_CONTEXT,
                "announcement": AnnouncementDTO.model_validate(announcement),
            },
        )

    def test_get_redirects_when_announcement_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="Other", content="C"
        )

        response = authenticated_client.get(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Announcement not found.")],
            url="/multiverse/panel/announcements/",
        )

    def test_post_deletes_announcement(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=sphere, title="Goner", content="C"
        )

        response = authenticated_client.post(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement deleted successfully.")],
            url="/multiverse/panel/announcements/",
        )
        assert not Announcement.objects.filter(pk=announcement.pk).exists()

    def test_post_redirects_when_announcement_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="Other", content="C"
        )

        response = authenticated_client.post(self.get_url(announcement))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Announcement not found.")],
            url="/multiverse/panel/announcements/",
        )
        assert Announcement.objects.filter(pk=announcement.pk).exists()


ACTIVE_SUBSCRIBERS = 2


class TestAnnouncementFanout:
    # Full loop with the cron-mode scheduler: the panel publish records intent
    # (log only) and the sweep — here driven directly — delivers the bell rows.
    create_url = reverse("multiverse:panel:announcement-create")

    @pytest.fixture(autouse=True)
    def _cron_scheduler(self, settings):
        settings.SCHEDULER_MODE = "cron"

    def _edit_url(self, pk):
        return reverse("multiverse:panel:announcement-edit", kwargs={"pk": pk})

    def test_publishing_notifies_each_active_subscriber_once(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        subscriber = UserFactory(username="subscriber")
        muted = UserFactory(username="muted")
        NotificationSubscription.objects.create(
            user=subscriber, sphere=sphere, source="visit"
        )
        NotificationSubscription.objects.create(
            user=muted, sphere=sphere, muted=True, source="visit"
        )

        authenticated_client.post(
            self.create_url,
            data={"title": "Hello", "content": "Body", "is_published": "on"},
        )
        # Two active subscribers: the seeded one plus the posting manager,
        # auto-subscribed by the visit middleware on their own request.
        assert build_announcement_fanout().fanout_due() == ACTIVE_SUBSCRIBERS

        notification = Notification.objects.get(recipient=subscriber)
        assert notification.kind == "announcement"
        assert notification.title == "Hello"
        assert notification.body == "Body"
        assert not notification.url
        assert not Notification.objects.filter(recipient=muted).exists()
        # Republishing the same announcement stays silent.
        announcement = Announcement.objects.get(sphere=sphere, title="Hello")
        for is_published in ({}, {"is_published": "on"}):
            authenticated_client.post(
                self._edit_url(announcement.pk),
                data={"title": "Hello", "content": "Body", **is_published},
            )
        assert build_announcement_fanout().fanout_due() == 0
        assert Notification.objects.filter(recipient=subscriber).count() == 1

    def test_draft_stays_silent_until_published(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        subscriber = UserFactory(username="subscriber")
        NotificationSubscription.objects.create(
            user=subscriber, sphere=sphere, source="visit"
        )

        authenticated_client.post(
            self.create_url, data={"title": "Hello", "content": "Body"}
        )
        assert build_announcement_fanout().fanout_due() == 0

        announcement = Announcement.objects.get(sphere=sphere)
        authenticated_client.post(
            self._edit_url(announcement.pk),
            data={"title": "Hello", "content": "Body", "is_published": "on"},
        )
        # The seeded subscriber plus the auto-subscribed posting manager.
        assert build_announcement_fanout().fanout_due() == ACTIVE_SUBSCRIBERS
        assert Notification.objects.filter(recipient=subscriber).count() == 1
