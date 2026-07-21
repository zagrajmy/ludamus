from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    ContentChangeLog,
    SessionField,
    SessionFieldRequirement,
    SessionFieldValue,
)
from ludamus.pacts import ContentChangeLogDTO, EventDTO
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
NOT_LATEST_ERROR = "Only the latest change for a session can be reverted."
NOT_REVERTIBLE_ERROR = (
    "This change cannot be reverted: cover image and assignment "
    "changes are not restorable."
)


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


def _log_dto(log):
    return ContentChangeLogDTO(
        pk=log.pk,
        event_id=log.event_id,
        session_id=log.session_id,
        session_title=log.session.title,
        user_id=log.user_id,
        user_name=log.user.name if log.user else "",
        changes=log.changes,
        creation_time=log.creation_time,
    )


def _edit(client, event, session, *, title, extra=None):
    return client.post(
        reverse(
            "panel:proposal-edit",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
        data={
            "category_id": session.category_id,
            "title": title,
            "display_name": "Original host",
            "participants_limit": 5,
            "min_age": 0,
            **(extra or {}),
        },
        follow=True,
    )


class TestContentLogRevertActionView:
    """Tests for /panel/event/<slug>/proposals/log/<pk>/revert/ endpoint."""

    @staticmethod
    def get_url(event, pk):
        return reverse(
            "panel:content-log-revert", kwargs={"slug": event.slug, "pk": pk}
        )

    @staticmethod
    def get_log_url(event):
        return reverse("panel:content-log", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, 1)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event, 1))

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
        url = reverse(
            "panel:content-log-revert", kwargs={"slug": "nonexistent", "pk": 1}
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_unknown_log_pk_shows_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event, 99999))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Change not found.")],
            url=self.get_log_url(event),
        )

    def test_revert_restores_core_and_dynamic_field(
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
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False, order=0
        )
        _edit(
            authenticated_client,
            event,
            session,
            title="Updated title",
            extra={"session_system": "Pathfinder"},
        )
        log = ContentChangeLog.objects.get(session=session)

        response = authenticated_client.post(self.get_url(event, log.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Change reverted.")],
            url=self.get_log_url(event),
        )
        session.refresh_from_db()
        assert session.title == "Original title"
        value = SessionFieldValue.objects.get(session=session, field=field)
        assert not value.value

    def test_revert_writes_its_own_log_row(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        _edit(authenticated_client, event, session, title="Updated title")
        log = ContentChangeLog.objects.get(session=session)

        authenticated_client.post(self.get_url(event, log.pk))

        logs = list(ContentChangeLog.objects.filter(session=session).order_by("pk"))
        assert len(logs) == 1 + 1  # the edit + its revert
        assert logs[1].user_id == active_user.pk
        assert {
            "field": "title",
            "field_id": None,
            "old": "Updated title",
            "new": "Original title",
        } in logs[1].changes

    def test_revert_non_latest_shows_error_and_mutates_nothing(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        _edit(authenticated_client, event, session, title="Second title")
        first_log = ContentChangeLog.objects.get(session=session)
        _edit(authenticated_client, event, session, title="Third title")

        response = authenticated_client.post(self.get_url(event, first_log.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, NOT_LATEST_ERROR)],
            url=self.get_log_url(event),
        )
        session.refresh_from_db()
        assert session.title == "Third title"
        # The two edits only — the rejected revert wrote nothing.
        assert ContentChangeLog.objects.filter(session=session).count() == 1 + 1

    def test_revert_log_from_another_event_shows_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_session = _make_session(ProposalCategoryFactory(event=other_event))
        _edit(authenticated_client, other_event, other_session, title="Updated title")
        log = ContentChangeLog.objects.get(session=other_session)

        response = authenticated_client.post(self.get_url(event, log.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Change not found.")],
            url=self.get_log_url(event),
        )
        other_session.refresh_from_db()
        assert other_session.title == "Updated title"
        assert ContentChangeLog.objects.filter(session=other_session).count() == 1

    def test_revert_cover_only_change_shows_not_revertible(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        log = ContentChangeLog.objects.create(
            event=event,
            session=session,
            user=active_user,
            changes=[
                {
                    "field": "cover_image",
                    "field_id": None,
                    "old": "",
                    "new": "(updated)",
                }
            ],
        )

        response = authenticated_client.post(self.get_url(event, log.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, NOT_REVERTIBLE_ERROR)],
            url=self.get_log_url(event),
        )
        session.refresh_from_db()
        assert session.title == "Original title"
        assert ContentChangeLog.objects.filter(session=session).count() == 1

    def test_revert_of_revert_restores_the_edit(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        _edit(authenticated_client, event, session, title="Updated title")
        first_log = ContentChangeLog.objects.get(session=session)

        authenticated_client.post(self.get_url(event, first_log.pk), follow=True)
        session.refresh_from_db()
        assert session.title == "Original title"

        revert_log = (
            ContentChangeLog.objects.filter(session=session).order_by("-pk").first()
        )
        assert revert_log.pk != first_log.pk

        response = authenticated_client.post(self.get_url(event, revert_log.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Change reverted.")],
            url=self.get_log_url(event),
        )
        session.refresh_from_db()
        assert session.title == "Updated title"
        assert (
            ContentChangeLog.objects.filter(session=session).count()
            == 1 + 1 + 1  # edit + revert + revert-of-revert
        )


class TestContentLogRevertButton:
    """The Revert button renders only on the latest row per session."""

    def test_button_only_on_latest_row_per_session(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = _make_session(proposal_category)
        _edit(authenticated_client, event, session, title="Second title")
        first_log = ContentChangeLog.objects.get(session=session)
        _edit(authenticated_client, event, session, title="Third title")
        latest_log = (
            ContentChangeLog.objects.filter(session=session).order_by("-pk").first()
        )

        response = authenticated_client.get(
            reverse("panel:content-log", kwargs={"slug": event.slug})
        )

        latest_url = reverse(
            "panel:content-log-revert", kwargs={"slug": event.slug, "pk": latest_log.pk}
        )
        first_url = reverse(
            "panel:content-log-revert", kwargs={"slug": event.slug, "pk": first_log.pk}
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/content-log.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "active_nav": "proposals",
                "slug": event.slug,
                "logs": [_log_dto(latest_log), _log_dto(first_log)],
                "field_names": {},
                "revertible_pks": {latest_log.pk},
                "facilitator_logs": [],
                "facilitator_field_names": {},
            },
            contains=latest_url,
            not_contains=first_url,
        )
