from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.links.db.django.models import (
    Connection,
    EventIntegration,
    Facilitator,
    ImportLogEntry,
    ProposalCategory,
    ScheduleChangeLog,
    Session,
    TimeSlot,
    Track,
)
from ludamus.pacts import (
    AgendaItemDTO,
    EventDTO,
    FacilitatorDTO,
    ScheduleChangeAction,
    ScheduleChangeLogDTO,
    SessionDTO,
    SessionStatus,
    TimeSlotDTO,
    TrackDTO,
)
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.submissions import ImportLogEntryDTO
from tests.integration.conftest import AgendaItemFactory, EventFactory, SpaceFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


class TestProposalDetailPageView:
    """Tests for /panel/event/<slug>/proposals/<proposal_id>/ page."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        category = ProposalCategory.objects.create(
            event=other_event, name="RPG", slug="rpg"
        )
        session = Session.objects.create(
            event=other_event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Other Event Session",
            slug="other-session",
            participants_limit=5,
            status="pending",
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_ok_when_session_has_no_presenter(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=None,
            display_name="Anonymous Host",
            title="Session Without Presenter",
            slug="no-presenter",
            participants_limit=5,
            status="pending",
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
        )

    def test_shows_cover_image(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Session With Cover",
            slug="with-cover",
            participants_limit=5,
            status="pending",
            cover_image=SimpleUploadedFile(
                "cover.png", PNG_BYTES, content_type="image/png"
            ),
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

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
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": UserDTO.model_validate(active_user),
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
        )
        assert session.cover_image_url.encode() in response.content

    def test_renders_contact_email_as_mailto_link_when_set(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Session With Email",
            slug="session-with-email",
            participants_limit=4,
            status="pending",
            contact_email="anna@example.com",
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=["Presenter", "Contact Email", 'href="mailto:anna@example.com"'],
        )

    def test_renders_preferred_time_slots_when_attached(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        slot = TimeSlot.objects.create(
            event=event,
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Session With Slots",
            slug="session-with-slots",
            participants_limit=4,
            status="pending",
        )
        session.time_slots.add(slot)

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [TimeSlotDTO.model_validate(slot)],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains="Preferred time slots",
        )

    def test_unscheduled_proposal_shows_metadata_without_placement(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Unscheduled",
            slug="unscheduled",
            participants_limit=4,
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
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=["Slug", "Created", "Last modified", "unscheduled"],
            not_contains=["View on timetable", "Schedule changes"],
        )

    def test_scheduled_proposal_shows_placement_with_timetable_link(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Scheduled",
            slug="scheduled-proposal",
            participants_limit=4,
            status="pending",
        )
        space = SpaceFactory(name="Main Hall", event=event)
        agenda_item = AgendaItemFactory(
            session=session,
            space=space,
            start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )
        timetable_url = reverse("panel:timetable", kwargs={"slug": event.slug})

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 1,
                    "scheduled_sessions": 1,
                    "total_proposals": 1,
                    "total_sessions": 2,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": AgendaItemDTO(
                    end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
                    pk=agenda_item.pk,
                    session_confirmed=False,
                    start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
                    space_id=space.pk,
                    space_name="Main Hall",
                    session_id=session.pk,
                    session_title="Scheduled",
                    session_description="",
                    presenter_name="Host",
                    session_duration_minutes=120,
                    session_status=SessionStatus.PENDING,
                    category_name="RPG",
                ),
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=[
                "View on timetable",
                "Main Hall",
                f'href="{timetable_url}?date=2026-07-01"',
            ],
        )

    def test_renders_schedule_change_log(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="With Log",
            slug="with-log",
            participants_limit=4,
            status="pending",
        )
        space = SpaceFactory(name="Main Hall", event=event)
        log = ScheduleChangeLog.objects.create(
            event=event,
            session=session,
            user=active_user,
            action="assign",
            new_space=space,
            new_start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            new_end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 1,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [
                    ScheduleChangeLogDTO(
                        pk=log.pk,
                        event_id=event.pk,
                        session_id=session.pk,
                        session_title="With Log",
                        user_id=active_user.pk,
                        user_name="Test User",
                        action=ScheduleChangeAction.ASSIGN,
                        old_space_id=None,
                        old_space_name=None,
                        new_space_id=space.pk,
                        new_space_name="Main Hall",
                        old_start_time=None,
                        old_end_time=None,
                        new_start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
                        new_end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
                        creation_time=log.creation_time,
                    )
                ],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=["Schedule changes", "Assigned", "Main Hall"],
        )

    def test_renders_schedule_log_space_moves_and_removals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="With Log",
            slug="with-log",
            participants_limit=4,
            status="pending",
        )
        old_space = SpaceFactory(name="Alpha Room", event=event)
        new_space = SpaceFactory(name="Beta Room", event=event)
        ScheduleChangeLog.objects.create(
            event=event,
            session=session,
            user=active_user,
            action="revert",
            old_space=old_space,
            new_space=new_space,
        )
        ScheduleChangeLog.objects.create(
            event=event,
            session=session,
            user=active_user,
            action="unassign",
            old_space=old_space,
            new_space=None,
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Alpha Room" in content
        assert "Beta Room" in content
        assert "Reverted" in content
        assert "Removed" in content

    def test_unscheduled_proposal_renders_status_buttons(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Pending Proposal",
            slug="pending-proposal",
            participants_limit=4,
            status="pending",
        )
        url_kwargs = {"slug": event.slug, "proposal_id": session.pk}

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=[
                reverse("panel:proposal-accept", kwargs=url_kwargs),
                reverse("panel:proposal-hold", kwargs=url_kwargs),
                reverse("panel:proposal-reject", kwargs=url_kwargs),
                'disabled title="This is the current status."',
            ],
            not_contains=[reverse("panel:proposal-pending", kwargs=url_kwargs)],
        )

    def test_scheduled_proposal_disables_non_accept_status_buttons(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Scheduled Proposal",
            slug="scheduled-proposal",
            participants_limit=4,
            status="accepted",
        )
        space = SpaceFactory(name="Main Hall", event=event)
        agenda_item = AgendaItemFactory(
            session=session,
            space=space,
            start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )
        url_kwargs = {"slug": event.slug, "proposal_id": session.pk}
        scheduled_tooltip = (
            "This session is scheduled and can only be accepted. "
            "Remove it from the timetable to change its status."
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 1,
                    "scheduled_sessions": 1,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": AgendaItemDTO(
                    end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
                    pk=agenda_item.pk,
                    session_confirmed=False,
                    start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
                    space_id=space.pk,
                    space_name="Main Hall",
                    session_id=session.pk,
                    session_title="Scheduled Proposal",
                    session_description="",
                    presenter_name="Host",
                    session_duration_minutes=120,
                    session_status=SessionStatus.ACCEPTED,
                    category_name="RPG",
                ),
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=[
                f'disabled title="{scheduled_tooltip}"',
                'disabled title="This is the current status."',
            ],
            not_contains=[
                reverse("panel:proposal-pending", kwargs=url_kwargs),
                reverse("panel:proposal-hold", kwargs=url_kwargs),
                reverse("panel:proposal-reject", kwargs=url_kwargs),
                reverse("panel:proposal-accept", kwargs=url_kwargs),
            ],
        )

    def test_facilitators_card_links_to_facilitator_detail(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Session With Facilitator",
            slug="session-with-facilitator",
            participants_limit=4,
            status="pending",
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        facilitator_url = reverse(
            "panel:facilitator-detail",
            kwargs={"slug": event.slug, "facilitator_slug": "alice"},
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [FacilitatorDTO.model_validate(facilitator)],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=[f'href="{facilitator_url}"', "Alice"],
        )

    def test_renders_track_chips_linking_to_track_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        track = Track.objects.create(
            event=event, name="Main Track", slug="main-track", is_public=True
        )
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Session With Track",
            slug="session-with-track",
            participants_limit=4,
            status="pending",
        )
        session.tracks.add(track)
        track_url = reverse(
            "panel:track-edit", kwargs={"slug": event.slug, "track_slug": track.slug}
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [TrackDTO.model_validate(track)],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": None,
                "import_log_integration": None,
            },
            contains=[f'href="{track_url}"', "Main Track"],
        )

    def test_imported_proposal_renders_back_link_to_log(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Anonymous",
            title="Imported session",
            slug="imported",
            participants_limit=5,
            status="pending",
        )
        connection = Connection.objects.create(sphere=sphere, display_name="API key")
        integration = EventIntegration.objects.create(
            event=event,
            kind=IntegrationKind.IMPORT.value,
            implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER.value,
            connection=connection,
            display_name="Puller",
        )
        entry = ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json="{}",
            title="Imported session",
            session=session,
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        log_url = reverse(
            "panel:import-log", kwargs={"slug": event.slug, "pk": integration.pk}
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "category_name": "RPG",
                "proposal_tracks": [],
                "agenda_item": None,
                "schedule_logs": [],
                "field_values": [],
                "facilitators": [],
                "presenter": None,
                "preferred_time_slots": [],
                "import_log_entry": ImportLogEntryDTO.model_validate(entry),
                "import_log_integration": EventIntegrationDTO(
                    pk=integration.pk,
                    event_id=event.pk,
                    kind=IntegrationKind.IMPORT,
                    implementation=(IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER),
                    connection_id=connection.pk,
                    connection_display_name="API key",
                    display_name="Puller",
                    config_json="{}",
                    settings_json="{}",
                    questions_snapshot_json="[]",
                ),
            },
            contains=[f'href="{log_url}?focus={entry.pk}"', "Imported via Puller"],
        )

    def test_log_view_highlights_focused_entry_and_opens_successes(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(sphere=sphere, display_name="API key")
        integration = EventIntegration.objects.create(
            event=event,
            kind=IntegrationKind.IMPORT.value,
            implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER.value,
            connection=connection,
            display_name="Puller",
        )
        session = Session.objects.create(
            event=event,
            title="Focused",
            slug="focused",
            status="pending",
            participants_limit=0,
        )
        entry = ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json="{}",
            title="Focused",
            session=session,
        )

        log_url = reverse(
            "panel:import-log", kwargs={"slug": event.slug, "pk": integration.pk}
        )
        response = authenticated_client.get(f"{log_url}?focus={entry.pk}")

        # Forced open: the focused success entry forces the <details> open and
        # gets the CSS highlight in the body.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import-log.html",
            context_data={
                **_base_context(event),
                "active_nav": "import",
                "active_integration": EventIntegrationDTO(
                    pk=integration.pk,
                    event_id=event.pk,
                    kind=IntegrationKind.IMPORT,
                    implementation=(IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER),
                    connection_id=connection.pk,
                    connection_display_name="API key",
                    display_name="Puller",
                    config_json="{}",
                    settings_json="{}",
                    questions_snapshot_json="[]",
                ),
                "active_tab": "log",
                "tab_urls": {
                    "proposal": reverse(
                        "panel:import-integration",
                        kwargs={"slug": event.slug, "pk": integration.pk},
                    ),
                    "review": reverse(
                        "panel:import-review",
                        kwargs={"slug": event.slug, "pk": integration.pk},
                    ),
                    "json": reverse(
                        "panel:import-json",
                        kwargs={"slug": event.slug, "pk": integration.pk},
                    ),
                    "run": reverse(
                        "panel:import-run",
                        kwargs={"slug": event.slug, "pk": integration.pk},
                    ),
                    "log": log_url,
                },
                "log_status": "all",
                "log_search": "",
                "log_focus_pk": entry.pk,
                "log_filter_urls": {
                    "all": f"{log_url}?status=all",
                    "skipped": f"{log_url}?status=skipped",
                    "success": f"{log_url}?status=success",
                },
                "log_show_errors": True,
                "log_show_successes": True,
                "log_successes_open": True,
                "log_errors": [],
                "log_successes": [ImportLogEntryDTO.model_validate(entry)],
                "log_total_attempts": 1,
                "log_success_count": 1,
                "log_error_count": 0,
            },
            contains=[f'id="entry-{entry.pk}"', "ring-2 ring-primary"],
        )
