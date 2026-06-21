from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldValue,
    Track,
)
from ludamus.pacts import (
    EventDTO,
    SessionDTO,
    SessionFieldDTO,
    SessionFieldValueDTO,
    SessionListItemDTO,
    SessionStatus,
    TrackDTO,
    UserDTO,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


_TRACK_FILTER_CONTEXT = {
    "all_tracks": [],
    "managed_track_pks": set(),
    "filter_track_pk": None,
}


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "proposals",
    }


class TestProposalsPageView:
    """Tests for /panel/event/<slug>/proposals/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:proposals", kwargs={"slug": event.slug})

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

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse("panel:proposals", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_for_sphere_manager_empty(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "proposals": [],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "",
            },
        )

    def test_shows_rejected_and_scheduled_status_badges(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Rejected One",
            slug="rejected-one",
            sphere=sphere,
            participants_limit=5,
            status="rejected",
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Scheduled One",
            slug="scheduled-one",
            sphere=sphere,
            participants_limit=5,
            status="scheduled",
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Rejected" in content
        assert "Scheduled" in content

    def test_returns_proposals_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="My Session",
            slug="my-session",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session.pk,
                        title="My Session",
                        display_name=active_user.name,
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session.creation_time,
                    )
                ],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "",
            },
        )

    def test_search_matches_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Session A",
            slug="session-a",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        session_pseudonym = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name="Mysterious Stranger",
            title="Session B",
            slug="session-b",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )

        response = authenticated_client.get(
            self.get_url(event), {"search": "Mysterious"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session_pseudonym.pk,
                        title="Session B",
                        display_name="Mysterious Stranger",
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session_pseudonym.creation_time,
                    )
                ],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "Mysterious",
            },
        )

    def test_search_matches_host_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        other_user = UserFactory(username="other", name="Other Person")
        Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Session A",
            slug="session-a",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        session_b = Session.objects.create(
            event=event,
            category=category,
            presenter=other_user,
            display_name="Other Person",
            title="Session B",
            slug="session-b",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )

        response = authenticated_client.get(self.get_url(event), {"search": "Other"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 2,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session_b.pk,
                        title="Session B",
                        display_name="Other Person",
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session_b.creation_time,
                    )
                ],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "Other",
            },
        )

    def test_filters_by_session_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="What system?",
            slug="system",
            field_type="select",
        )
        session1 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="D&D Adventure",
            slug="dnd-adventure",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session1, field=field, value="D&D 5e")
        session2 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Fate Adventure",
            slug="fate-adventure",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session2, field=field, value="Fate Core"
        )

        response = authenticated_client.get(
            self.get_url(event), {f"field_{field.pk}": "D&D 5e"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session1.pk,
                        title="D&D Adventure",
                        display_name=active_user.name,
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session1.creation_time,
                    )
                ],
                "session_fields": [
                    SessionFieldDTO(
                        pk=field.pk,
                        name="System",
                        question="What system?",
                        slug="system",
                        field_type="select",
                        order=0,
                    )
                ],
                "filter_fields": {field.pk: "D&D 5e"},
                "filter_search": "",
            },
        )

    def test_filters_by_session_field_with_polish_characters(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event,
            name="Treści",
            question="Treści?",
            slug="tresci",
            field_type="select",
        )
        session1 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Mroczna sesja",
            slug="mroczna-sesja",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session1, field=field, value="przekleństwa"
        )
        session2 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Inna sesja",
            slug="inna-sesja",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session2, field=field, value="przemoc")

        response = authenticated_client.get(
            self.get_url(event), {f"field_{field.pk}": "przekleństwa"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session1.pk,
                        title="Mroczna sesja",
                        display_name=active_user.name,
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session1.creation_time,
                    )
                ],
                "session_fields": [
                    SessionFieldDTO(
                        pk=field.pk,
                        name="Treści",
                        question="Treści?",
                        slug="tresci",
                        field_type="select",
                        order=0,
                    )
                ],
                "filter_fields": {field.pk: "przekleństwa"},
                "filter_search": "",
            },
        )

    def test_search_across_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="What system?",
            slug="system",
            field_type="text",
        )
        session1 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="D&D Adventure",
            slug="dnd-adventure",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session1, field=field, value="D&D 5e")
        session2 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Fate Adventure",
            slug="fate-adventure",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session2, field=field, value="Fate Core"
        )

        response = authenticated_client.get(self.get_url(event), {"search": "D&D"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session1.pk,
                        title="D&D Adventure",
                        display_name=active_user.name,
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session1.creation_time,
                    )
                ],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "D&D",
            },
        )

    def test_search_with_polish_characters(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event,
            name="Treści",
            question="Treści?",
            slug="tresci",
            field_type="text",
        )
        session1 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Mroczna sesja",
            slug="mroczna-sesja",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session1, field=field, value="Zawiera przekleństwa"
        )
        session2 = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Inna sesja",
            slug="inna-sesja",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session2, field=field, value="Zawiera przemoc"
        )

        response = authenticated_client.get(
            self.get_url(event), {"search": "przekleństwa"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "proposals": [
                    SessionListItemDTO(
                        pk=session1.pk,
                        title="Mroczna sesja",
                        display_name=active_user.name,
                        category_name="RPG",
                        status=SessionStatus.PENDING,
                        creation_time=session1.creation_time,
                    )
                ],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "przekleństwa",
            },
        )

    def test_auto_selects_single_managed_track_when_no_track_param(
        self, authenticated_client, active_user, sphere, event
    ):
        """Single managed track is auto-selected when no track param is given."""
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="My Track", slug="my-track", is_public=True
        )
        track.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                "proposals": [],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "",
                "all_tracks": [TrackDTO.model_validate(track)],
                "managed_track_pks": {track.pk},
                "filter_track_pk": track.pk,
            },
        )

    def test_filters_by_numeric_track_param(
        self, authenticated_client, active_user, sphere, event
    ):
        """When track param is a digit string, it is parsed as filter_track_pk."""
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Alpha Track", slug="alpha-track", is_public=True
        )

        response = authenticated_client.get(
            self.get_url(event), {"track": str(track.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                "proposals": [],
                "session_fields": [],
                "filter_fields": {},
                "filter_search": "",
                "all_tracks": [TrackDTO.model_validate(track)],
                "managed_track_pks": set(),
                "filter_track_pk": track.pk,
            },
        )

    def test_excludes_text_fields_from_filters(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        SessionField.objects.create(
            event=event,
            name="Notes",
            question="Any notes?",
            slug="notes",
            field_type="text",
        )
        select_field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Pick genre",
            slug="genre",
            field_type="select",
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data={
                **_base_context(event),
                "deleted_proposals": [],
                **_TRACK_FILTER_CONTEXT,
                "proposals": [],
                "session_fields": [
                    SessionFieldDTO(
                        pk=select_field.pk,
                        name="Genre",
                        question="Pick genre",
                        slug="genre",
                        field_type="select",
                        order=0,
                    )
                ],
                "filter_fields": {select_field.pk: ""},
                "filter_search": "",
            },
        )


class TestProposalDetailPageView:
    """Tests for /panel/event/<slug>/proposals/<id>/ page."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, 999)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event, 999))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:proposal-detail", kwargs={"slug": "nonexistent", "proposal_id": 999}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_redirects_for_missing_proposal(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, 99999))

        proposals_url = reverse("panel:proposals", kwargs={"slug": event.slug})
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=proposals_url,
        )

    def test_shows_proposal_details(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="My Great Session",
            description="A wonderful adventure",
            slug="my-great-session",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "active_nav": "proposals",
                "proposal": SessionDTO.model_validate(session),
                "field_values": [],
                "facilitators": [],
                "presenter": UserDTO.model_validate(active_user),
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
        )

    def test_shows_field_values(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event, name="System", question="What RPG system?", slug="system"
        )
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="My Session",
            slug="my-session",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session, field=field, value="D&D 5e")

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 1,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "active_nav": "proposals",
                "proposal": SessionDTO.model_validate(session),
                "field_values": [
                    SessionFieldValueDTO(
                        field_id=field.pk,
                        field_name="System",
                        field_question="What RPG system?",
                        field_slug="system",
                        value="D&D 5e",
                    )
                ],
                "facilitators": [],
                "presenter": UserDTO.model_validate(active_user),
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
        )

    def test_formats_list_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event,
            name="Genres",
            question="What genres?",
            slug="genres",
            field_type="select",
        )
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="My Session",
            slug="my-session",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(
            session=session, field=field, value=["RPG", "Popculture"]
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "RPG, Popculture" in content
        assert '["RPG"' not in content
