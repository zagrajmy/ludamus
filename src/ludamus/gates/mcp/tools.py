"""Maintainer MCP tool set.

A hand-curated surface, not an auto-export of every service: each tool is a
deliberate maintainer operation. All calls go through `ServicesProtocol`, so
business invariants hold for MCP callers exactly as they do for views.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from django.utils.text import slugify
from pydantic import BaseModel, Field, TypeAdapter, field_validator

from ludamus.gates.mcp.registry import Tool, ToolError, ToolRegistry
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import SessionPlacement
from ludamus.pacts.event import FacilitatorListItemDTO
from ludamus.pacts.legacy import (
    EventDTO,
    EventListItemDTO,
    SessionListItemDTO,
    TimeSlotDTO,
    TrackListItemDTO,
)
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    EventDatesInvalidError,
    EventSlugConflictError,
    SphereListItemDTO,
)
from ludamus.pacts.panel import (
    FacilitatorCreateData,
    FacilitatorListQuery,
    ProposalDraft,
    ProposalListQuery,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import AccreditationType
from ludamus.pacts.venues import SpaceInputDTO, SpaceTreeNodeDTO

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolCall, ToolProtocol
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

_SPHERE_LIST = TypeAdapter(list[SphereListItemDTO])
_EVENT_LIST = TypeAdapter(list[EventListItemDTO])
_ANNOUNCEMENT_LIST = TypeAdapter(list[AnnouncementDTO])


class _EmptyInput(BaseModel):
    pass


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        message = f"{field} must be timezone-aware"
        raise ValueError(message)
    return value


def _validate_slug(value: str) -> str:
    stripped = value.strip()
    if not stripped or "/" in stripped:
        raise ValueError("slug must be a non-empty URL slug without '/'")
    return stripped


_AUDIT_REDACTED_KEYS: dict[str, frozenset[str]] = {
    "find_or_create_facilitator": frozenset({"display_name"}),
    "create_session": frozenset({"display_name", "description"}),
}


def sanitize_audit_arguments(
    tool_name: str, arguments: dict[str, object]
) -> dict[str, object]:
    redact = _AUDIT_REDACTED_KEYS.get(tool_name)
    if redact is None:
        return arguments
    return {
        key: "[redacted]" if key in redact else value
        for key, value in arguments.items()
    }


class _AwareDatetimeRange(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_datetimes(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field="datetime")


def _render_sphere(services: ServicesProtocol, sphere_id: int) -> str:
    return services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


def _render_events(
    *, services: ServicesProtocol, sphere_id: int, include_unpublished: bool
) -> str:
    events = services.events.list_for_sphere(
        sphere_id, include_unpublished=include_unpublished
    )
    return _EVENT_LIST.dump_json(events, indent=2).decode()


def _render_announcements(services: ServicesProtocol, sphere_id: int) -> str:
    items = services.announcements.list_for_sphere(sphere_id)
    return _ANNOUNCEMENT_LIST.dump_json(items, indent=2).decode()


def _create_announcement(
    *, services: ServicesProtocol, sphere_id: int, body: _AnnouncementBody
) -> str:
    created = services.announcements.create(sphere_id, _announcement_data(body))
    return created.model_dump_json(indent=2)


def _update_announcement(
    *,
    services: ServicesProtocol,
    sphere_id: int,
    announcement_id: int,
    body: _AnnouncementBody,
) -> str:
    updated = services.announcements.update(
        sphere_id, announcement_id, _announcement_data(body)
    )
    return updated.model_dump_json(indent=2)


def _delete_announcement(
    *, services: ServicesProtocol, sphere_id: int, announcement_id: int
) -> str:
    services.announcements.delete(sphere_id, announcement_id)
    result: dict[str, int] = {"deleted": announcement_id}
    return json.dumps(result)


class _SphereInput(BaseModel):
    sphere_id: int = Field(description="Sphere primary key (see list_spheres)")


class ListSpheresTool(Tool[_EmptyInput]):
    name = "list_spheres"
    description = (
        "List every sphere (community site) with its id, name and domain. "
        "Call this first to discover sphere ids used by the other tools."
    )
    scope = ToolScope.MAINTAINER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        spheres = call.services.sites.list_spheres()
        return _SPHERE_LIST.dump_json(spheres, indent=2).decode()


class GetSphereTool(Tool[_SphereInput]):
    name = "get_sphere"
    description = "Read one sphere's settings and configuration."
    scope = ToolScope.MAINTAINER
    input_model = _SphereInput

    @staticmethod
    def handle(call: ToolCall[_SphereInput]) -> str:
        return _render_sphere(call.services, call.data.sphere_id)


class _ListEventsBody(BaseModel):
    include_unpublished: bool = Field(
        default=True, description="Include events that are not published yet"
    )


class _ListEventsInput(_SphereInput, _ListEventsBody):
    pass


class ListEventsTool(Tool[_ListEventsInput]):
    name = "list_events"
    description = "List a sphere's events with their status and session counts."
    scope = ToolScope.MAINTAINER
    input_model = _ListEventsInput

    @staticmethod
    def handle(call: ToolCall[_ListEventsInput]) -> str:
        return _render_events(
            services=call.services,
            sphere_id=call.data.sphere_id,
            include_unpublished=call.data.include_unpublished,
        )


class _GetEventInput(_SphereInput):
    slug: str = Field(description="Event slug (see list_events)")


class GetEventTool(Tool[_GetEventInput]):
    name = "get_event"
    description = "Read one event's full configuration by slug."
    scope = ToolScope.MAINTAINER
    input_model = _GetEventInput

    @staticmethod
    def handle(call: ToolCall[_GetEventInput]) -> str:
        event: EventDTO = call.services.events.read_by_slug(
            call.data.sphere_id, call.data.slug
        )
        return event.model_dump_json(indent=2)


class ListAnnouncementsTool(Tool[_SphereInput]):
    name = "list_announcements"
    description = "List a sphere's announcements, published and drafts."
    scope = ToolScope.MAINTAINER
    input_model = _SphereInput

    @staticmethod
    def handle(call: ToolCall[_SphereInput]) -> str:
        return _render_announcements(call.services, call.data.sphere_id)


class _AnnouncementBody(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(max_length=50000)
    is_published: bool = Field(
        default=False, description="Publish immediately; false saves a draft"
    )


class _AnnouncementContentInput(_SphereInput, _AnnouncementBody):
    pass


class CreateAnnouncementTool(Tool[_AnnouncementContentInput]):
    name = "create_announcement"
    description = "Create a sphere announcement (draft by default)."
    scope = ToolScope.MAINTAINER
    input_model = _AnnouncementContentInput

    @staticmethod
    def handle(call: ToolCall[_AnnouncementContentInput]) -> str:
        return _create_announcement(
            services=call.services, sphere_id=call.data.sphere_id, body=call.data
        )


class _UpdateAnnouncementInput(_AnnouncementContentInput):
    announcement_id: int


class UpdateAnnouncementTool(Tool[_UpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.MAINTAINER
    input_model = _UpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_UpdateAnnouncementInput]) -> str:
        return _update_announcement(
            services=call.services,
            sphere_id=call.data.sphere_id,
            announcement_id=call.data.announcement_id,
            body=call.data,
        )


class _DeleteAnnouncementInput(_SphereInput):
    announcement_id: int


class DeleteAnnouncementTool(Tool[_DeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement permanently."
    scope = ToolScope.MAINTAINER
    input_model = _DeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_DeleteAnnouncementInput]) -> str:
        return _delete_announcement(
            services=call.services,
            sphere_id=call.data.sphere_id,
            announcement_id=call.data.announcement_id,
        )


def _announcement_data(body: _AnnouncementBody) -> AnnouncementData:
    return AnnouncementData(
        title=body.title, content=body.content, is_published=body.is_published
    )


def _actor_sphere(actor: ActorContext) -> int:
    if actor.sphere_id is None:
        raise ToolError("Token carries no sphere scope")
    return actor.sphere_id


class OrganizerGetSphereTool(Tool[_EmptyInput]):
    name = "get_sphere"
    description = "Read your sphere's settings and configuration."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_sphere(call.services, _actor_sphere(call.actor))


class OrganizerListEventsTool(Tool[_ListEventsBody]):
    name = "list_events"
    description = "List your sphere's events with their status and session counts."
    scope = ToolScope.ORGANIZER
    input_model = _ListEventsBody

    @staticmethod
    def handle(call: ToolCall[_ListEventsBody]) -> str:
        return _render_events(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            include_unpublished=call.data.include_unpublished,
        )


class OrganizerListAnnouncementsTool(Tool[_EmptyInput]):
    name = "list_announcements"
    description = "List your sphere's announcements, published and drafts."
    scope = ToolScope.ORGANIZER
    input_model = _EmptyInput

    @staticmethod
    def handle(call: ToolCall[_EmptyInput]) -> str:
        return _render_announcements(call.services, _actor_sphere(call.actor))


class OrganizerCreateAnnouncementTool(Tool[_AnnouncementBody]):
    name = "create_announcement"
    description = "Create an announcement in your sphere (draft by default)."
    scope = ToolScope.ORGANIZER
    input_model = _AnnouncementBody

    @staticmethod
    def handle(call: ToolCall[_AnnouncementBody]) -> str:
        return _create_announcement(
            services=call.services, sphere_id=_actor_sphere(call.actor), body=call.data
        )


class _OrgUpdateAnnouncementInput(_AnnouncementBody):
    announcement_id: int


class OrganizerUpdateAnnouncementTool(Tool[_OrgUpdateAnnouncementInput]):
    name = "update_announcement"
    description = "Update an announcement's title, content or published flag."
    scope = ToolScope.ORGANIZER
    input_model = _OrgUpdateAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgUpdateAnnouncementInput]) -> str:
        return _update_announcement(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            announcement_id=call.data.announcement_id,
            body=call.data,
        )


class _OrgDeleteAnnouncementInput(BaseModel):
    announcement_id: int


class OrganizerDeleteAnnouncementTool(Tool[_OrgDeleteAnnouncementInput]):
    name = "delete_announcement"
    description = "Delete an announcement from your sphere permanently."
    scope = ToolScope.ORGANIZER
    input_model = _OrgDeleteAnnouncementInput

    @staticmethod
    def handle(call: ToolCall[_OrgDeleteAnnouncementInput]) -> str:
        return _delete_announcement(
            services=call.services,
            sphere_id=_actor_sphere(call.actor),
            announcement_id=call.data.announcement_id,
        )


class _EventSlugInput(BaseModel):
    slug: str = Field(description="Event slug (see list_events)")


class OrganizerGetEventTool(Tool[_EventSlugInput]):
    name = "get_event"
    description = "Read one event in your sphere by slug."
    scope = ToolScope.ORGANIZER
    input_model = _EventSlugInput

    @staticmethod
    def handle(call: ToolCall[_EventSlugInput]) -> str:
        event: EventDTO = call.services.events.read_by_slug(
            _actor_sphere(call.actor), call.data.slug
        )
        return event.model_dump_json(indent=2)


class _CreateEventInput(BaseModel):
    name: str = Field(max_length=255)
    slug: str = Field(max_length=50, description="URL slug; unique within the sphere")
    description: str = ""
    start_time: datetime
    end_time: datetime
    publication_time: datetime | None = Field(
        default=None, description="None keeps the event unpublished"
    )
    auto_confirm_sessions: bool = Field(
        default=False,
        description="Confirm sessions when first assigned to the timetable",
    )

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_event_datetimes(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, field="datetime")

    @field_validator("publication_time")
    @classmethod
    def _aware_publication_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_aware_datetime(value, field="publication_time")


class OrganizerCreateEventTool(Tool[_CreateEventInput]):
    name = "create_event"
    description = "Create an event in your sphere."
    scope = ToolScope.ORGANIZER
    input_model = _CreateEventInput

    @staticmethod
    def handle(call: ToolCall[_CreateEventInput]) -> str:
        try:
            event = call.services.events.create(
                sphere_id=_actor_sphere(call.actor),
                data={
                    "name": call.data.name,
                    "slug": call.data.slug,
                    "description": call.data.description,
                    "start_time": call.data.start_time,
                    "end_time": call.data.end_time,
                    "publication_time": call.data.publication_time,
                    "auto_confirm_sessions": call.data.auto_confirm_sessions,
                },
            )
        except EventDatesInvalidError as error:
            raise ToolError("end_time must be after start_time") from error
        except EventSlugConflictError as error:
            message = f"Slug already taken: {call.data.slug}"
            raise ToolError(message) from error
        return event.model_dump_json(indent=2)


class _EventIdInput(BaseModel):
    event_id: int = Field(
        description="Event primary key (see create_event / get_event)"
    )


def _require_event(call: ToolCall[_EventIdInput]) -> EventDTO:
    return call.services.events.require_in_sphere(
        sphere_id=_actor_sphere(call.actor), event_id=call.data.event_id
    )


class _SpaceLeaf(BaseModel):
    pk: int
    name: str
    path: str
    capacity: int | None
    parent_id: int | None


def _flatten_leaves(
    nodes: list[SpaceTreeNodeDTO], *, prefix: str = ""
) -> list[_SpaceLeaf]:
    leaves: list[_SpaceLeaf] = []
    for node in nodes:
        path = f"{prefix} > {node.space.name}" if prefix else node.space.name
        if node.is_leaf:
            leaves.append(
                _SpaceLeaf(
                    pk=node.space.pk,
                    name=node.space.name,
                    path=path,
                    capacity=node.space.capacity,
                    parent_id=node.space.parent_id,
                )
            )
        leaves.extend(_flatten_leaves(node.children, prefix=path))
    return leaves


class OrganizerListSpacesTool(Tool[_EventIdInput]):
    name = "list_spaces"
    description = (
        "List leaf spaces (rooms) for an event, with path labels through the "
        "venue/area tree."
    )
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        leaves = _flatten_leaves(call.services.space_tree.list_tree(event.pk))
        return TypeAdapter(list[_SpaceLeaf]).dump_json(leaves, indent=2).decode()


class OrganizerListTimeSlotsTool(Tool[_EventIdInput]):
    name = "list_time_slots"
    description = "List time slots (day windows) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        slots = call.services.panel_time_slots.list_for_event(event.pk)
        return TypeAdapter(list[TimeSlotDTO]).dump_json(slots, indent=2).decode()


class OrganizerListTracksTool(Tool[_EventIdInput]):
    name = "list_tracks"
    description = "List programme tracks (bloki) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        tracks = call.services.tracks_panel.list_tracks(event.pk)
        return TypeAdapter(list[TrackListItemDTO]).dump_json(tracks, indent=2).decode()


class OrganizerListSessionsTool(Tool[_EventIdInput]):
    name = "list_sessions"
    description = "List proposals/sessions for an event (for idempotent retries)."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        context = call.services.proposal_panel.list_context(
            event_id=event.pk, query=ProposalListQuery()
        )
        return (
            TypeAdapter(list[SessionListItemDTO])
            .dump_json(context.proposals, indent=2)
            .decode()
        )


class OrganizerListFacilitatorsTool(Tool[_EventIdInput]):
    name = "list_facilitators"
    description = "List facilitators (twórcy programu) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        context = call.services.facilitator_panel.list_context(
            event_id=event.pk, query=FacilitatorListQuery()
        )
        return (
            TypeAdapter(list[FacilitatorListItemDTO])
            .dump_json(context.facilitators, indent=2)
            .decode()
        )


class _CreateSpaceInput(_EventIdInput):
    name: str = Field(max_length=255)
    parent_id: int | None = Field(
        default=None, description="Null creates a venue root; otherwise nest under it"
    )
    capacity: int | None = None
    description: str = ""
    location: str = ""


class OrganizerCreateSpaceTool(Tool[_CreateSpaceInput]):
    name = "create_space"
    description = (
        "Create a space in an event's venue tree. parent_id null = venue root; "
        "leaves hold sessions."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateSpaceInput

    @staticmethod
    def handle(call: ToolCall[_CreateSpaceInput]) -> str:
        event = _require_event(call)
        if call.data.parent_id is not None:
            parent = call.services.space_tree.read(call.data.parent_id)
            if parent.event_id != event.pk:
                raise NotFoundError
        space = call.services.space_tree.create(
            event_id=event.pk,
            parent_id=call.data.parent_id,
            data=SpaceInputDTO(
                name=call.data.name,
                capacity=call.data.capacity,
                description=call.data.description,
                location=call.data.location,
            ),
        )
        return space.model_dump_json(indent=2)


class _CreateTimeSlotInput(_EventIdInput, _AwareDatetimeRange):
    pass


class OrganizerCreateTimeSlotTool(Tool[_CreateTimeSlotInput]):
    name = "create_time_slot"
    description = "Create a day time-slot window for an event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateTimeSlotInput

    @staticmethod
    def handle(call: ToolCall[_CreateTimeSlotInput]) -> str:
        event = _require_event(call)
        errors = call.services.panel_time_slots.create(
            event=event, start_time=call.data.start_time, end_time=call.data.end_time
        )
        if errors:
            raise ToolError(", ".join(error.value for error in errors))
        slots = call.services.panel_time_slots.list_for_event(event.pk)
        created = next(
            slot
            for slot in slots
            if slot.start_time == call.data.start_time
            and slot.end_time == call.data.end_time
        )
        return created.model_dump_json(indent=2)


class _CreateTrackInput(_EventIdInput):
    name: str = Field(max_length=255)
    is_public: bool = True
    space_ids: list[int] = Field(default_factory=list)
    manager_ids: list[int] = Field(default_factory=list)


class OrganizerCreateTrackTool(Tool[_CreateTrackInput]):
    name = "create_track"
    description = "Create a programme track (blok) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateTrackInput

    @staticmethod
    def handle(call: ToolCall[_CreateTrackInput]) -> str:
        event = _require_event(call)
        call.services.tracks_panel.create(
            event_pk=event.pk,
            sphere_id=_actor_sphere(call.actor),
            data={
                "name": call.data.name,
                "is_public": call.data.is_public,
                "space_pks": call.data.space_ids,
                "manager_pks": call.data.manager_ids,
            },
        )
        tracks = call.services.tracks_panel.list_tracks(event.pk)
        created = next(track for track in tracks if track.name == call.data.name)
        return created.model_dump_json(indent=2)


class _CreateProposalCategoryInput(_EventIdInput):
    name: str = Field(max_length=255)


class OrganizerCreateProposalCategoryTool(Tool[_CreateProposalCategoryInput]):
    name = "create_proposal_category"
    description = "Create a proposal category (rodzaj atrakcji) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateProposalCategoryInput

    @staticmethod
    def handle(call: ToolCall[_CreateProposalCategoryInput]) -> str:
        event = _require_event(call)
        category = call.services.proposal_categories.create(event.pk, call.data.name)
        return category.model_dump_json(indent=2)


class _FindOrCreateFacilitatorInput(_EventIdInput):
    display_name: str = Field(max_length=255)


class OrganizerFindOrCreateFacilitatorTool(Tool[_FindOrCreateFacilitatorInput]):
    name = "find_or_create_facilitator"
    description = (
        "Find a facilitator by exact display name within an event, or create one."
    )
    scope = ToolScope.ORGANIZER
    input_model = _FindOrCreateFacilitatorInput

    @staticmethod
    def handle(call: ToolCall[_FindOrCreateFacilitatorInput]) -> str:
        event = _require_event(call)
        context = call.services.facilitator_panel.list_context(
            event_id=event.pk, query=FacilitatorListQuery(search=call.data.display_name)
        )
        for facilitator in context.facilitators:
            if facilitator.display_name == call.data.display_name:
                return facilitator.model_dump_json(indent=2)
        created = call.services.facilitator_panel.create_facilitator(
            event_id=event.pk,
            data=FacilitatorCreateData(
                display_name=call.data.display_name,
                base_slug=slugify(call.data.display_name),
                accreditation_type=AccreditationType.NONE,
            ),
            user_id=call.actor.user_id,
        )
        return created.model_dump_json(indent=2)


class _CreateSessionInput(_EventIdInput):
    source_row_id: str = Field(
        max_length=64, description="Deterministic idempotency key for this source row"
    )
    title: str = Field(max_length=255)
    category_id: int
    description: str = ""
    duration: str = Field(
        default="", description="ISO-8601 duration, e.g. PT1H or PT45M"
    )
    display_name: str = Field(default="", description="Defaults to title when empty")
    facilitator_ids: list[int] = Field(default_factory=list)
    track_ids: list[int] = Field(default_factory=list)
    participants_limit: int = 0
    min_age: int = 0


class OrganizerCreateSessionTool(Tool[_CreateSessionInput]):
    name = "create_session"
    description = (
        "Create an accepted session (punkt programu) ready for timetable assign."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateSessionInput

    @staticmethod
    def handle(call: ToolCall[_CreateSessionInput]) -> str:
        event = _require_event(call)
        categories = {
            category.pk
            for category in call.services.proposal_categories.get_page_context(
                event.pk
            ).categories
        }
        if call.data.category_id not in categories:
            raise NotFoundError
        known_facilitators = {
            item.pk
            for item in call.services.facilitator_panel.list_context(
                event_id=event.pk, query=FacilitatorListQuery()
            ).facilitators
        }
        if any(pk not in known_facilitators for pk in call.data.facilitator_ids):
            raise NotFoundError
        known_tracks = {
            track.pk for track in call.services.tracks_panel.list_tracks(event.pk)
        }
        if any(pk not in known_tracks for pk in call.data.track_ids):
            raise NotFoundError
        title = call.data.title
        try:
            session_id = call.services.proposal_panel.create_accepted_session(
                event_id=event.pk,
                source_row_id=call.data.source_row_id.strip(),
                draft=ProposalDraft(
                    data={
                        "category_id": call.data.category_id,
                        "event_id": event.pk,
                        "contact_email": "",
                        "description": call.data.description,
                        "display_name": call.data.display_name or title,
                        "duration": call.data.duration,
                        "min_age": call.data.min_age,
                        "participants_limit": call.data.participants_limit,
                        "presenter_id": None,
                        "title": title,
                    },
                    base_slug=slugify(title),
                    facilitator_ids=call.data.facilitator_ids,
                    track_ids=call.data.track_ids,
                ),
            )
        except DatabaseConstraintError as error:
            raise ToolError("Could not create session") from error
        session = call.services.proposal_panel.read_proposal(
            event_id=event.pk, proposal_id=session_id
        )
        return session.model_dump_json(indent=2)


class _AssignSessionInput(_EventIdInput, _AwareDatetimeRange):
    session_id: int
    space_id: int


class OrganizerAssignSessionTool(Tool[_AssignSessionInput]):
    name = "assign_session"
    description = "Place an accepted session into a space and time window."
    scope = ToolScope.ORGANIZER
    input_model = _AssignSessionInput

    @staticmethod
    def handle(call: ToolCall[_AssignSessionInput]) -> str:
        event = _require_event(call)
        try:
            call.services.timetable.assign_session(
                session_pk=call.data.session_id,
                placement=SessionPlacement(
                    space_pk=call.data.space_id,
                    start_time=call.data.start_time,
                    end_time=call.data.end_time,
                ),
                event_pk=event.pk,
                user_pk=call.actor.user_id,
            )
        except ValueError as error:
            raise ToolError(str(error)) from error
        result: dict[str, int] = {
            "session_id": call.data.session_id,
            "space_id": call.data.space_id,
        }
        return json.dumps(result)


def _all_tools() -> tuple[ToolProtocol, ...]:
    return (
        ListSpheresTool(),
        GetSphereTool(),
        ListEventsTool(),
        GetEventTool(),
        ListAnnouncementsTool(),
        CreateAnnouncementTool(),
        UpdateAnnouncementTool(),
        DeleteAnnouncementTool(),
        OrganizerGetSphereTool(),
        OrganizerListEventsTool(),
        OrganizerGetEventTool(),
        OrganizerCreateEventTool(),
        OrganizerListSpacesTool(),
        OrganizerListTimeSlotsTool(),
        OrganizerListTracksTool(),
        OrganizerListSessionsTool(),
        OrganizerListFacilitatorsTool(),
        OrganizerCreateSpaceTool(),
        OrganizerCreateTimeSlotTool(),
        OrganizerCreateTrackTool(),
        OrganizerCreateProposalCategoryTool(),
        OrganizerFindOrCreateFacilitatorTool(),
        OrganizerCreateSessionTool(),
        OrganizerAssignSessionTool(),
        OrganizerListAnnouncementsTool(),
        OrganizerCreateAnnouncementTool(),
        OrganizerUpdateAnnouncementTool(),
        OrganizerDeleteAnnouncementTool(),
    )


def build_registry(scope: ToolScope) -> ToolRegistry:
    return ToolRegistry([tool for tool in _all_tools() if tool.scope == scope])
