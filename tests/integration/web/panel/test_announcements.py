"""Integration tests for the event announcements panel pages and delete action."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Announcement
from ludamus.pacts.multiverse import AnnouncementDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)

NOT_FOUND_ERROR = "Announcement not found."


def make_announcement(event, *, title="Doors open at 9", is_published=True):
    return Announcement.objects.create(
        event=event, title=title, content="Body", is_published=is_published
    )


class TestAnnouncementsPageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:announcements", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_on_invalid_event_slug(self, panel_client):
        url = reverse("panel:announcements", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_ok_empty(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcements.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "announcements": [],
            },
        )

    def test_get_lists_drafts_and_published(self, panel_client, event):
        draft = make_announcement(event, title="Draft", is_published=False)
        published = make_announcement(event, title="Live")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcements.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "announcements": [
                    AnnouncementDTO.model_validate(published),
                    AnnouncementDTO.model_validate(draft),
                ],
            },
        )

    def test_get_excludes_other_events(self, panel_client, event, non_root_sphere):
        # Another sphere's event, so the sidebar's event list stays unchanged
        # and the only thing under test is the announcement scope.
        make_announcement(EventFactory(sphere=non_root_sphere), title="Elsewhere")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcements.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "announcements": [],
            },
        )


class TestAnnouncementCreatePageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:announcement-create", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_ok(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcement-form.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "form": ANY,
                "announcement_pk": None,
            },
        )

    def test_post_creates_announcement(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event),
            {"title": "Doors open at 9", "content": "Be early.", "is_published": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement created.")],
            url=f"/panel/event/{event.slug}/announcements/",
        )
        announcement = Announcement.objects.get()
        assert announcement.event_id == event.pk
        assert announcement.sphere_id is None
        assert announcement.title == "Doors open at 9"
        assert announcement.is_published is True

    def test_post_creates_draft_when_unpublished(self, panel_client, event):
        panel_client.post(
            self.get_url(event), {"title": "Later", "content": "Not yet."}
        )

        assert Announcement.objects.get().is_published is False

    def test_post_rerenders_form_on_invalid_input(self, panel_client, event):
        response = panel_client.post(self.get_url(event), {"title": "", "content": ""})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcement-form.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "form": ANY,
                "announcement_pk": None,
            },
        )
        assert not Announcement.objects.exists()


class TestAnnouncementEditPageView:
    @staticmethod
    def get_url(event, announcement):
        return reverse(
            "panel:announcement-edit",
            kwargs={"slug": event.slug, "pk": announcement.pk},
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, make_announcement(event))

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(
            self.get_url(event, make_announcement(event))
        )

        assert_not_a_manager(response)

    def test_get_ok(self, panel_client, event):
        announcement = make_announcement(event)

        response = panel_client.get(self.get_url(event, announcement))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcement-form.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "form": ANY,
                "announcement_pk": announcement.pk,
            },
        )

    def test_get_redirects_for_another_events_announcement(
        self, panel_client, event, sphere
    ):
        foreign = make_announcement(EventFactory(sphere=sphere))

        response = panel_client.get(self.get_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, NOT_FOUND_ERROR)],
            url=f"/panel/event/{event.slug}/announcements/",
        )

    def test_post_updates_announcement(self, panel_client, event):
        announcement = make_announcement(event)

        response = panel_client.post(
            self.get_url(event, announcement),
            {"title": "Doors open at 10", "content": "Changed.", "is_published": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement updated.")],
            url=f"/panel/event/{event.slug}/announcements/",
        )
        announcement.refresh_from_db()
        assert announcement.title == "Doors open at 10"
        assert announcement.content == "Changed."

    def test_post_rerenders_form_on_invalid_input(self, panel_client, event):
        announcement = make_announcement(event)

        response = panel_client.post(
            self.get_url(event, announcement), {"title": "", "content": ""}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/announcement-form.html",
            context_data={
                **panel_context(event, active_nav="announcements"),
                "form": ANY,
                "announcement_pk": announcement.pk,
            },
        )
        announcement.refresh_from_db()
        assert announcement.title == "Doors open at 9"

    def test_post_leaves_another_events_announcement_untouched(
        self, panel_client, event, sphere
    ):
        foreign = make_announcement(EventFactory(sphere=sphere))

        response = panel_client.post(
            self.get_url(event, foreign),
            {"title": "Hijacked", "content": "Nope.", "is_published": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, NOT_FOUND_ERROR)],
            url=f"/panel/event/{event.slug}/announcements/",
        )
        foreign.refresh_from_db()
        assert foreign.title == "Doors open at 9"


class TestAnnouncementDeleteActionView:
    @staticmethod
    def get_url(event, announcement):
        return reverse(
            "panel:announcement-delete",
            kwargs={"slug": event.slug, "pk": announcement.pk},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, make_announcement(event))

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event, make_announcement(event))
        )

        assert_not_a_manager(response)

    def test_post_deletes_announcement(self, panel_client, event):
        announcement = make_announcement(event)

        response = panel_client.post(self.get_url(event, announcement))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Announcement deleted.")],
            url=f"/panel/event/{event.slug}/announcements/",
        )
        assert not Announcement.objects.filter(pk=announcement.pk).exists()

    def test_post_keeps_another_events_announcement(self, panel_client, event, sphere):
        foreign = make_announcement(EventFactory(sphere=sphere))

        response = panel_client.post(self.get_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, NOT_FOUND_ERROR)],
            url=f"/panel/event/{event.slug}/announcements/",
        )
        assert Announcement.objects.filter(pk=foreign.pk).exists()

    def test_get_not_allowed(self, panel_client, event):
        response = panel_client.get(self.get_url(event, make_announcement(event)))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
