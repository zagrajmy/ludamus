from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Announcement
from ludamus.pacts.multiverse import AnnouncementDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "connections": "/multiverse/panel/connections/",
    "announcements": "/multiverse/panel/announcements/",
    "mcp": "/multiverse/panel/mcp/",
}
ANNOUNCEMENTS_PANEL_CONTEXT = {
    "events": [],
    "current_event": None,
    "is_proposal_active": False,
    "active_nav": "sphere-settings",
    "active_tab": "announcements",
    "tab_urls": TAB_URLS,
}


class TestAnnouncementsPageView:
    url = reverse("multiverse:panel:announcements")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

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

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

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
            contains="this.querySelector('button[type=submit]').disabled = true",
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
