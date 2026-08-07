import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.agenda_item import AgendaItemRepository
from ludamus.links.db.django.models import (
    EventIntegration,
    Facilitator,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldRequirement,
)
from ludamus.pacts import (
    EventDTO,
    FacilitatorListItemDTO,
    SessionDTO,
    SessionStatus,
    SpaceDTO,
)
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
    SessionPositionDTO,
    SpaceColumnDTO,
    SpaceGroupDTO,
    TimeLabelDTO,
    TimetableDayGridDTO,
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
from tests.integration.utils import PageMatcher, assert_response

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

PROPOSAL_PAGE_SIZES = [10, 20, 50, 100]
PROPOSAL_STATUSES = [
    ("pending", "Pending"),
    ("accepted", "Accepted"),
    ("on_hold", "On hold"),
    ("rejected", "Rejected"),
    ("scheduled", "Scheduled"),
]

# Filter/pagination keys the proposal list renders with no query string: the
# status filter defaults to pending.
PROPOSAL_FILTER_CONTEXT = {
    "all_tracks": [],
    "managed_track_pks": set(),
    "filter_track_pk": None,
    "filter_track_multi": False,
    "filter_track_value": "",
    "page_obj": PageMatcher(number=1, num_pages=1),
    "page_sizes": PROPOSAL_PAGE_SIZES,
    "filter_category_pk": None,
    "filter_status": SessionStatus.PENDING,
    "filter_status_value": SessionStatus.PENDING,
    "filter_sort": "",
    "statuses": PROPOSAL_STATUSES,
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


def grid_with(
    *,
    spaces,
    day_start=None,
    extra_days=0,
    total_minutes=0,
    sessions_by_space=None,
    page=1,
    total_pages=1,
    total_spaces=None,
    date_selection="all",
):
    # The expected timetable grid for the rendered days of top-level rooms.
    # Callers pass the first day's first label time and its span in minutes
    # rather than the slots, so no test re-derives the view's slot-window
    # bounds. `extra_days` repeats that window on the following days, which is
    # what a multi-day event with one slot per day renders.
    space_dtos = [SpaceDTO.model_validate(space) for space in spaces]
    sessions = sessions_by_space or {}
    labels = (
        [
            TimeLabelDTO(
                time=day_start + timedelta(minutes=offset), offset_minutes=offset
            )
            for offset in range(0, total_minutes + 1, TIMETABLE_SLOT_MINUTES)
        ]
        if day_start
        else []
    )
    day_starts = (
        [day_start + timedelta(days=offset) for offset in range(extra_days + 1)]
        if day_start
        else []
    )
    days = [
        TimetableDayGridDTO(
            date=start.date(),
            columns=[
                SpaceColumnDTO(
                    space=space,
                    # A block sits on one day, and `sessions_by_space` places
                    # it on the first one.
                    sessions=sessions.get(space.pk, []) if index == 0 else [],
                )
                for space in space_dtos
            ],
            event_start_iso=start.isoformat(),
        )
        for index, start in enumerate(day_starts)
    ]
    return TimetableGridDTO(
        spaces=space_dtos,
        groups=(
            [SpaceGroupDTO(parent_pk=None, parent_name="", span=len(space_dtos))]
            if space_dtos
            else []
        ),
        days=days,
        time_labels=labels,
        total_minutes=total_minutes,
        slot_minutes=TIMETABLE_SLOT_MINUTES,
        snap_minutes=TIMETABLE_SNAP_MINUTES,
        page=page,
        total_pages=total_pages,
        total_spaces=len(space_dtos) if total_spaces is None else total_spaces,
        total_columns=len(space_dtos) * len(days),
        available_dates=[day.date for day in days],
        date_selection=date_selection,
    )


def empty_grid():
    return grid_with(spaces=[])


def session_position(
    item, *, start_minutes, duration_minutes, visible_minutes=None, state="normal"
):
    # These tests assert where an agenda item lands in the grid; the item's own
    # field mapping is the repository's contract, tested there, so read it back
    # instead of restating a dozen fields.
    return SessionPositionDTO(
        agenda_item=AgendaItemRepository.read(item.pk),
        start_minutes=start_minutes,
        duration_minutes=duration_minutes,
        visible_minutes=(
            duration_minutes if visible_minutes is None else visible_minutes
        ),
        state=state,
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
