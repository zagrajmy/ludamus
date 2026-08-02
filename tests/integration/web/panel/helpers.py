"""Shared arrange/assert helpers for panel integration tests."""

import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    EventIntegration,
    Facilitator,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldRequirement,
)
from ludamus.pacts import EventDTO, FacilitatorListItemDTO, SessionDTO
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
    TimetableGridDTO,
)
from ludamus.pacts.crowd import UserDTO
from ludamus.specs.timetable import TIMETABLE_SLOT_MINUTES, TIMETABLE_SNAP_MINUTES
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
)
from tests.integration.utils import assert_response

if TYPE_CHECKING:
    from django.http import HttpResponse

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
EVENT_NOT_FOUND_ERROR = "Event not found."
PROPOSAL_NOT_FOUND_ERROR = "Proposal not found."
SCHEDULED_ERROR = (
    "This session is scheduled and can only be accepted. "
    "Remove it from the timetable to change its status."
)

EMPTY_STATS = {
    "hosts_count": 0,
    "pending_proposals": 0,
    "rooms_count": 0,
    "scheduled_sessions": 0,
    "total_proposals": 0,
    "total_sessions": 0,
}


def panel_context(event, *, active_nav: str | None = None, **stats: int) -> dict:
    # Every panel page renders the sidebar from these keys. Pass stats that
    # differ from empty as keyword arguments: panel_context(event, rooms_count=2)
    context = {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": EMPTY_STATS | stats,
    }
    if active_nav:
        context["active_nav"] = active_nav
    return context


def assert_not_a_manager(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PERMISSION_ERROR)],
        url="/",
    )


def assert_event_not_found(response: HttpResponse) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, EVENT_NOT_FOUND_ERROR)],
        url="/panel/",
    )


def assert_proposal_not_found(response: HttpResponse, event) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, PROPOSAL_NOT_FOUND_ERROR)],
        url=reverse("panel:proposals", kwargs={"slug": event.slug}),
    )


def assert_scheduled_proposal_refused(
    *, response: HttpResponse, event, session
) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, SCHEDULED_ERROR)],
        url=reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
    )


def assert_proposal_status_applied(
    *, response: HttpResponse, event, session, message: str, status: str
) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.SUCCESS, message)],
        url=reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
    )
    session.refresh_from_db()
    assert session.status == status, session.status


def assert_proposal_status_unchanged(session, status: str) -> None:
    session.refresh_from_db()
    assert session.status == status, session.status


def make_facilitator(event, **kwargs):
    defaults = {"display_name": "Alice", "slug": "alice", "user": None}
    return Facilitator.objects.create(event=event, **(defaults | kwargs))


def make_workshop_and_talk(event):
    # The two categories the field-create pages offer for assignment.
    return (
        ProposalCategoryFactory(event=event, name="Workshop"),
        ProposalCategoryFactory(event=event, name="Talk"),
    )


def make_scheduled_proposal(event):
    # An accepted proposal already on the timetable — the state every status
    # action refuses to change.
    session = make_proposal(event, status="accepted")
    AgendaItemFactory(
        session=session,
        space=SpaceFactory(event=event),
        start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
        end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
    )
    return session


def schedule_session(*, session, space, start, hours=1):
    return AgendaItemFactory(
        session=session,
        space=space,
        start_time=start,
        end_time=start + timedelta(hours=hours),
    )


def make_overlapping_sessions(event, category):
    # Two sessions in the same room at the same hour: the minimal conflict.
    space = SpaceFactory(event=event)
    sessions = [make_timetable_session(category) for _ in range(2)]
    for session in sessions:
        schedule_session(session=session, space=space, start=event.start_time)
    return space, sessions


def schedule_outside_preferred_slot(*, event, category, space):
    # Scheduled at the event start while its only preferred slot sits hours
    # later: a slot violation, which the conflict panel deliberately ignores.
    session = make_timetable_session(category)
    session.time_slots.add(
        TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=4),
            end_time=event.start_time + timedelta(hours=6),
        )
    )
    schedule_session(session=session, space=space, start=event.start_time)
    return session


def make_timetable_session(category, *, status="pending", participants_limit=5):
    return SessionFactory(
        category=category,
        status=status,
        participants_limit=participants_limit,
        min_age=0,
    )


def assign_payload(*, session, space, start, end):
    return {
        "session_pk": session.pk,
        "space_pk": space.pk,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }


def empty_grid():
    return TimetableGridDTO(
        spaces=[],
        groups=[],
        days=[],
        time_labels=[],
        total_minutes=0,
        slot_minutes=TIMETABLE_SLOT_MINUTES,
        snap_minutes=TIMETABLE_SNAP_MINUTES,
        page=1,
        total_pages=1,
        total_spaces=0,
        total_columns=0,
        available_dates=[],
    )


def cfp_tab_urls(event):
    return {
        "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
        "host": reverse("panel:personal-data-fields", kwargs={"slug": event.slug}),
        "session": reverse("panel:session-fields", kwargs={"slug": event.slug}),
        "time_slots": reverse("panel:time-slots", kwargs={"slug": event.slug}),
    }


def timetable_tab_urls(event):
    return {
        "timetable": reverse("panel:timetable", kwargs={"slug": event.slug}),
        "log": reverse("panel:timetable-log", kwargs={"slug": event.slug}),
        "overview": reverse("panel:timetable-overview", kwargs={"slug": event.slug}),
        "problems": reverse("panel:timetable-problems", kwargs={"slug": event.slug}),
        "confirmations": reverse(
            "panel:timetable-confirmations", kwargs={"slug": event.slug}
        ),
    }


def assert_facilitator_not_found(response: HttpResponse, event) -> None:
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, "Facilitator not found.")],
        url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
    )


def proposal_detail_context(*, event, session, presenter) -> dict:
    # One proposal by one host: the counts the sidebar derives from it are
    # fixed, so they belong with the rest of the detail-page context.
    return {
        **panel_context(
            event,
            active_nav="proposals",
            hosts_count=1,
            pending_proposals=1,
            total_proposals=1,
            total_sessions=1,
        ),
        "proposal": SessionDTO.model_validate(session),
        "category_name": "RPG",
        "proposal_tracks": [],
        "agenda_item": None,
        "schedule_logs": [],
        "field_values": [],
        "facilitators": [],
        "presenter": UserDTO.model_validate(presenter),
        "preferred_time_slots": [],
        "import_log_entry": None,
        "import_log_integration": None,
    }


def facilitator_list_item_dto(facilitator, *, session_count=0):
    return FacilitatorListItemDTO(
        accreditation_type=facilitator.accreditation_type,
        display_name=facilitator.display_name,
        pk=facilitator.pk,
        session_count=session_count,
        slug=facilitator.slug,
        user_id=facilitator.user_id,
    )


def make_optional_session_field(*, event, category, slug="system", name="System"):
    field = SessionField.objects.create(
        event=event,
        name=name,
        question="Which system?",
        slug=slug,
        field_type="text",
        order=0,
    )
    SessionFieldRequirement.objects.create(
        category=category, field=field, is_required=False, order=0
    )
    return field


IMPORT_IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
IMPORT_CONFIG_JSON = json.dumps({"sheet_id": "sheet-1", "form_id": "form-1"})


def make_integration(event, connection, *, display_name: str) -> EventIntegration:
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.IMPORT.value,
        implementation=IMPORT_IMPL.value,
        connection=connection,
        display_name=display_name,
        config_json=IMPORT_CONFIG_JSON,
    )


def integration_dto(integration: EventIntegration) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        pk=integration.pk,
        event_id=integration.event_id,
        kind=IntegrationKind(integration.kind),
        implementation=IntegrationImplementationId(integration.implementation),
        connection_id=integration.connection_id,
        connection_display_name=integration.connection.display_name,
        display_name=integration.display_name,
        config_json=integration.config_json,
        settings_json=integration.settings_json,
        questions_snapshot_json=integration.questions_snapshot_json or "[]",
    )


def make_proposal(event, **kwargs):
    # The pending RPG proposal the panel action tests all start from.
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )
    return Session.objects.create(
        **{
            "event": event,
            "category": category,
            "presenter": None,
            "display_name": "Test Host",
            "title": "Test Session",
            "slug": "test-session",
            "participants_limit": 5,
            "status": "pending",
            **kwargs,
        }
    )
