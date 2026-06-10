from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import ContentChangeLog, SessionField
from tests.integration.conftest import SessionFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_session(sphere, proposal_category):
    return SessionFactory(
        category=proposal_category,
        sphere=sphere,
        status="pending",
        title="Original title",
        display_name="Original host",
        description="",
        requirements="",
        needs="",
        contact_email="",
        duration="",
        participants_limit=5,
        min_age=0,
    )


class TestContentLogPageView:
    """Tests for /panel/event/<slug>/proposals/log/ activity log page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:content-log", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:content-log", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_renders_empty_log(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.templates[0].name == "panel/content-log.html"
        assert response.context["logs"] == []
        assert response.context["active_nav"] == "proposals"


class TestContentLogRecordsEdits:
    """A proposal edit through the panel writes a content-change-log row."""

    def test_editing_a_proposal_records_core_field_changes(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(sphere, proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "title": "Updated title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert log.event_id == event.pk
        assert log.user_id == active_user.pk
        assert {
            "field": "title",
            "label": "Title",
            "old": "Original title",
            "new": "Updated title",
        } in log.changes

    def test_editing_a_session_field_records_field_change(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(sphere, proposal_category)
        SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "title": "Original title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
                "session_field_system": "Pathfinder",
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert {
            "field": "system",
            "label": "System",
            "old": None,
            "new": "Pathfinder",
        } in log.changes

    def test_no_change_writes_no_log(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(sphere, proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "title": "Original title",
                "display_name": "Original host",
                "description": "",
                "requirements": "",
                "needs": "",
                "contact_email": "",
                "participants_limit": 5,
                "min_age": 0,
                "duration": "",
            },
        )

        assert not ContentChangeLog.objects.filter(session=session).exists()

    def test_edit_appears_in_log_view(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(sphere, proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "title": "Updated title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        response = authenticated_client.get(
            reverse("panel:content-log", kwargs={"slug": event.slug})
        )

        assert response.status_code == HTTPStatus.OK
        logs = response.context["logs"]
        assert len(logs) == 1
        assert logs[0].session_title == "Updated title"
        assert logs[0].user_name == active_user.name
