from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    ContentChangeLog,
    Facilitator,
    FacilitatorChangeLog,
    PersonalDataField,
    SessionField,
)
from tests.integration.conftest import SessionFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_session(proposal_category):
    return SessionFactory(
        category=proposal_category,
        status="pending",
        title="Original title",
        display_name="Original host",
        description="",
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
        session = _make_session(proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "category_id": session.category_id,
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
            "field_id": None,
            "old": "Original title",
            "new": "Updated title",
        } in log.changes

    def test_editing_facilitators_records_m2m_change(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "category_id": session.category_id,
                "title": "Original title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "facilitator_ids": [alice.pk],
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert {
            "field": "facilitators",
            "field_id": None,
            "old": "",
            "new": "Alice",
        } in log.changes

    def test_resubmitting_same_facilitators_logs_no_m2m_change(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(alice)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "category_id": session.category_id,
                "title": "Updated title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "facilitator_ids": [alice.pk],
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert not any(c["field"] == "facilitators" for c in log.changes)

    def test_facilitator_edit_logs_accreditation_and_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = Facilitator.objects.create(
            event=event,
            display_name="Alice",
            slug="alice",
            user=None,
            accreditation_type="none",
        )
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            reverse(
                "panel:facilitator-edit",
                kwargs={"slug": event.slug, "facilitator_slug": "alice"},
            ),
            data={"accreditation_type": "honorary", "personal_vegan": "true"},
        )

        log = FacilitatorChangeLog.objects.get(facilitator=facilitator)
        assert log.user_id == active_user.pk
        assert {
            "field": "accreditation_type",
            "field_id": None,
            "old": "none",
            "new": "honorary",
        } in log.changes
        assert {
            "field": "",
            "field_id": field.pk,
            "old": None,
            "new": True,
        } in log.changes

    def test_facilitator_changes_render_on_content_log_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = Facilitator.objects.create(
            event=event,
            display_name="Alice",
            slug="alice",
            user=None,
            accreditation_type="none",
        )

        authenticated_client.post(
            reverse(
                "panel:facilitator-edit",
                kwargs={"slug": event.slug, "facilitator_slug": "alice"},
            ),
            data={"accreditation_type": "honorary"},
        )
        response = authenticated_client.get(
            reverse("panel:content-log", kwargs={"slug": event.slug})
        )

        assert response.status_code == HTTPStatus.OK
        assert len(response.context["facilitator_logs"]) == 1
        assert response.context["facilitator_logs"][0].facilitator_id == facilitator.pk
        assert "Facilitator changes" in response.content.decode()

    def test_facilitator_personal_data_field_name_renders_on_log_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event,
            display_name="Alice",
            slug="alice",
            user=None,
            accreditation_type="none",
        )
        PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            reverse(
                "panel:facilitator-edit",
                kwargs={"slug": event.slug, "facilitator_slug": "alice"},
            ),
            data={"accreditation_type": "none", "personal_vegan": "true"},
        )
        response = authenticated_client.get(
            reverse("panel:content-log", kwargs={"slug": event.slug})
        )

        assert response.status_code == HTTPStatus.OK
        assert "Vegan" in response.content.decode()

    def test_editing_a_session_field_records_field_change(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        field = SessionField.objects.create(
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
                "category_id": session.category_id,
                "title": "Original title",
                "display_name": "Original host",
                "participants_limit": 5,
                "min_age": 0,
                "session_fields_submitted": "1",
                "session_field_system": "Pathfinder",
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert {
            "field": "",
            "field_id": field.pk,
            "old": None,
            "new": "Pathfinder",
        } in log.changes

    def test_no_change_writes_no_log(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "category_id": session.category_id,
                "title": "Original title",
                "display_name": "Original host",
                "description": "",
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
        session = _make_session(proposal_category)

        authenticated_client.post(
            reverse(
                "panel:proposal-edit",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
            data={
                "category_id": session.category_id,
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
