from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from django.utils.text import slugify
from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, field_validator

from ludamus.gates.mcp.organizer_context import actor_sphere, token_event
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import SessionPlacement
from ludamus.pacts.durations import normalize_duration
from ludamus.pacts.event import FacilitatorListItemDTO
from ludamus.pacts.legacy import (
    EventDTO,
    ProposalCategoryDTO,
    SessionListItemDTO,
    TimeSlotDTO,
    TrackListItemDTO,
)
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.panel import (
    FacilitatorCreateData,
    FacilitatorListQuery,
    ProposalDraft,
    ProposalListQuery,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import AccreditationType
from ludamus.pacts.timetable import PlacementRejectedError
from ludamus.pacts.venues import SpaceInputDTO, SpaceTreeNodeDTO, SpaceValidationError

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

_PROPOSAL_CATEGORY_LIST = TypeAdapter(list[ProposalCategoryDTO])
_JSON_OBJECT = TypeAdapter(dict[str, object])
type _NonBlankName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class _AwareDatetimeRange(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _aware_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime must be timezone-aware")
        return value


class _EventIdInput(BaseModel):
    event_id: int = Field(description="Event primary key (see list_events / get_event)")


def _require_event(call: ToolCall[_EventIdInput]) -> EventDTO:
    return call.services.events.require_in_sphere(
        sphere_id=actor_sphere(call.actor), event_id=call.data.event_id
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


class OrganizerListProposalCategoriesTool(Tool[_EventIdInput]):
    name = "list_proposal_categories"
    description = "List proposal categories for an event in this token's sphere."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        _require_event(call)
        context = call.services.proposal_categories.get_page_context(call.data.event_id)
        return _PROPOSAL_CATEGORY_LIST.dump_json(context.categories, indent=2).decode()


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


class _CreateSpaceInput(BaseModel):
    name: _NonBlankName
    parent_id: int | None = Field(
        default=None, description="Null creates a venue root; otherwise nest under it"
    )
    capacity: int | None = Field(default=None, ge=0)
    description: str = ""
    location: str = ""


class OrganizerCreateSpaceTool(Tool[_CreateSpaceInput]):
    name = "create_space"
    description = (
        "Create a space in this token's event venue tree. parent_id null = "
        "venue root; leaves hold sessions."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateSpaceInput

    @staticmethod
    def handle(call: ToolCall[_CreateSpaceInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        try:
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
        except SpaceValidationError as error:
            raise ToolError(str(error)) from error
        return space.model_dump_json(indent=2)


class _CreateTimeSlotInput(_AwareDatetimeRange):
    pass


class OrganizerCreateTimeSlotTool(Tool[_CreateTimeSlotInput]):
    name = "create_time_slot"
    description = "Create a day time-slot window for this token's event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateTimeSlotInput

    @staticmethod
    def handle(call: ToolCall[_CreateTimeSlotInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        errors, created = call.services.panel_time_slots.create(
            event=event, start_time=call.data.start_time, end_time=call.data.end_time
        )
        if errors:
            raise ToolError(", ".join(error.value for error in errors))
        if created is None:
            raise ToolError("Could not create time slot")
        return created.model_dump_json(indent=2)


class _CreateTrackInput(BaseModel):
    name: _NonBlankName
    is_public: bool = True
    space_ids: list[int] = Field(default_factory=list)
    manager_ids: list[int] = Field(default_factory=list)


class OrganizerCreateTrackTool(Tool[_CreateTrackInput]):
    name = "create_track"
    description = "Create a programme track (blok) for this token's event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateTrackInput

    @staticmethod
    def handle(call: ToolCall[_CreateTrackInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        created = call.services.tracks_panel.create(
            event_pk=event.pk,
            sphere_id=actor_sphere(call.actor),
            data={
                "name": call.data.name,
                "is_public": call.data.is_public,
                "space_pks": call.data.space_ids,
                "manager_pks": call.data.manager_ids,
            },
        )
        return created.model_dump_json(indent=2)


class _CreateProposalCategoryInput(BaseModel):
    name: _NonBlankName


class OrganizerCreateProposalCategoryTool(Tool[_CreateProposalCategoryInput]):
    name = "create_proposal_category"
    description = "Create a proposal category (rodzaj atrakcji) for this token's event."
    scope = ToolScope.ORGANIZER
    input_model = _CreateProposalCategoryInput

    @staticmethod
    def handle(call: ToolCall[_CreateProposalCategoryInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        category = call.services.proposal_categories.create(event.pk, call.data.name)
        return category.model_dump_json(indent=2)


class _FindOrCreateFacilitatorInput(BaseModel):
    display_name: _NonBlankName


class OrganizerFindOrCreateFacilitatorTool(Tool[_FindOrCreateFacilitatorInput]):
    name = "find_or_create_facilitator"
    description = (
        "Find a facilitator by exact display name in this token's event, or create one."
    )
    scope = ToolScope.ORGANIZER
    input_model = _FindOrCreateFacilitatorInput

    @staticmethod
    def handle(call: ToolCall[_FindOrCreateFacilitatorInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        facilitator = call.services.facilitator_panel.find_or_create_facilitator(
            event_id=event.pk,
            data=FacilitatorCreateData(
                display_name=call.data.display_name,
                base_slug=slugify(call.data.display_name),
                accreditation_type=AccreditationType.NONE,
            ),
            user_id=call.actor.user_id,
        )
        return facilitator.model_dump_json(indent=2)


class _CreateSessionInput(BaseModel):
    source_row_id: str = Field(
        max_length=64, description="Deterministic idempotency key for this source row"
    )

    @field_validator("source_row_id")
    @classmethod
    def _non_blank_source_row_id(cls, value: str) -> str:
        if not (stripped := value.strip()):
            raise ValueError("source_row_id must be non-empty")
        return stripped

    title: _NonBlankName
    category_id: int
    description: str = ""
    duration: str = Field(
        default="", description="ISO-8601 duration, e.g. PT1H or PT45M"
    )

    @field_validator("duration")
    @classmethod
    def _canonical_duration(cls, value: str) -> str:
        if not value:
            return ""
        if not (normalized := normalize_duration(value)):
            raise ValueError("duration must be a positive ISO-8601 duration")
        return normalized

    display_name: str = Field(default="", description="Defaults to title when empty")
    facilitator_ids: list[int] = Field(default_factory=list)
    track_ids: list[int] = Field(default_factory=list)
    participants_limit: int = 0
    min_age: int = 0


def _create_session(
    *, services: ServicesProtocol, event: EventDTO, data: _CreateSessionInput
) -> str:
    title = data.title
    try:
        session_id = services.proposal_panel.create_accepted_session(
            event_id=event.pk,
            source_row_id=data.source_row_id,
            draft=ProposalDraft(
                data={
                    "category_id": data.category_id,
                    "event_id": event.pk,
                    "contact_email": "",
                    "description": data.description,
                    "display_name": data.display_name or title,
                    "duration": data.duration,
                    "min_age": data.min_age,
                    "participants_limit": data.participants_limit,
                    "presenter_id": None,
                    "title": title,
                },
                base_slug=slugify(title),
                facilitator_ids=data.facilitator_ids,
                track_ids=data.track_ids,
            ),
        )
    except DatabaseConstraintError as error:
        raise ToolError("Could not create session") from error
    session = services.proposal_panel.read_proposal(
        event_id=event.pk, proposal_id=session_id
    )
    return session.model_dump_json(indent=2)


class OrganizerCreateSessionTool(Tool[_CreateSessionInput]):
    name = "create_session"
    description = (
        "Create an accepted session (punkt programu) in this token's event, "
        "ready for timetable assign."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateSessionInput

    @staticmethod
    def handle(call: ToolCall[_CreateSessionInput]) -> str:
        return _create_session(
            services=call.services,
            event=token_event(services=call.services, actor=call.actor),
            data=call.data,
        )


class _CreateSessionsInput(BaseModel):
    sessions: list[_CreateSessionInput] = Field(min_length=1, max_length=250)

    @field_validator("sessions")
    @classmethod
    def _unique_source_row_ids(
        cls, sessions: list[_CreateSessionInput]
    ) -> list[_CreateSessionInput]:
        source_row_ids = [session.source_row_id for session in sessions]
        if len(source_row_ids) != len(set(source_row_ids)):
            raise ValueError("source_row_id values must be unique within a batch")
        return sessions


class OrganizerCreateSessionsTool(Tool[_CreateSessionsInput]):
    name = "create_sessions"
    description = (
        "Create up to 250 accepted sessions (punkty programu) in this token's "
        "event. Results preserve input order; failed items do not roll back "
        "successful items and can be retried by source_row_id."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateSessionsInput

    @staticmethod
    def handle(call: ToolCall[_CreateSessionsInput]) -> str:
        results: list[dict[str, object]] = []
        failed = 0
        event = token_event(services=call.services, actor=call.actor)
        for index, session in enumerate(call.data.sessions):
            try:
                result = _create_session(
                    services=call.services, event=event, data=session
                )
            except NotFoundError:
                failed += 1
                results.append(
                    {
                        "index": index,
                        "source_row_id": session.source_row_id,
                        "status": "failed",
                        "error": "Resource not found",
                    }
                )
            except ToolError as error:
                failed += 1
                results.append(
                    {
                        "index": index,
                        "source_row_id": session.source_row_id,
                        "status": "failed",
                        "error": str(error),
                    }
                )
            else:
                results.append(
                    {
                        "index": index,
                        "source_row_id": session.source_row_id,
                        "status": "ok",
                        "session": _JSON_OBJECT.validate_json(result),
                    }
                )
        payload: dict[str, object] = {
            "summary": {
                "total": len(results),
                "succeeded": len(results) - failed,
                "failed": failed,
            },
            "results": results,
        }
        response = json.dumps(payload)
        if failed:
            raise ToolError(response)
        return response


class _AssignSessionInput(_AwareDatetimeRange):
    session_id: int
    space_id: int


def _assign_session(
    *,
    services: ServicesProtocol,
    actor: ActorContext,
    event: EventDTO,
    data: _AssignSessionInput,
) -> str:
    try:
        services.timetable.assign_session(
            session_pk=data.session_id,
            placement=SessionPlacement(
                space_pk=data.space_id,
                start_time=data.start_time,
                end_time=data.end_time,
            ),
            event_pk=event.pk,
            user_pk=actor.user_id,
        )
    except PlacementRejectedError as error:
        raise ToolError(str(error)) from error
    result: dict[str, int] = {"session_id": data.session_id, "space_id": data.space_id}
    return json.dumps(result)


class OrganizerAssignSessionTool(Tool[_AssignSessionInput]):
    name = "assign_session"
    description = (
        "Place an accepted session of this token's event into a space and time window."
    )
    scope = ToolScope.ORGANIZER
    input_model = _AssignSessionInput

    @staticmethod
    def handle(call: ToolCall[_AssignSessionInput]) -> str:
        return _assign_session(
            services=call.services,
            actor=call.actor,
            event=token_event(services=call.services, actor=call.actor),
            data=call.data,
        )


class _AssignSessionsInput(BaseModel):
    assignments: list[_AssignSessionInput] = Field(min_length=1, max_length=250)

    @field_validator("assignments")
    @classmethod
    def _unique_session_ids(
        cls, assignments: list[_AssignSessionInput]
    ) -> list[_AssignSessionInput]:
        session_ids = [assignment.session_id for assignment in assignments]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("session_id values must be unique within a batch")
        return assignments


class OrganizerAssignSessionsTool(Tool[_AssignSessionsInput]):
    name = "assign_sessions"
    description = (
        "Place up to 250 accepted sessions in this token's event. Results "
        "preserve input order; failed items do not roll back successful items."
    )
    scope = ToolScope.ORGANIZER
    input_model = _AssignSessionsInput

    @staticmethod
    def handle(call: ToolCall[_AssignSessionsInput]) -> str:
        results: list[dict[str, object]] = []
        failed = 0
        event = token_event(services=call.services, actor=call.actor)
        for index, assignment in enumerate(call.data.assignments):
            try:
                result = _assign_session(
                    services=call.services,
                    actor=call.actor,
                    event=event,
                    data=assignment,
                )
            except NotFoundError:
                failed += 1
                results.append(
                    {
                        "index": index,
                        "session_id": assignment.session_id,
                        "status": "failed",
                        "error": "Resource not found",
                    }
                )
            except ToolError as error:
                failed += 1
                results.append(
                    {
                        "index": index,
                        "session_id": assignment.session_id,
                        "status": "failed",
                        "error": str(error),
                    }
                )
            else:
                results.append(
                    {
                        "index": index,
                        "session_id": assignment.session_id,
                        "status": "ok",
                        "assignment": _JSON_OBJECT.validate_json(result),
                    }
                )
        payload: dict[str, object] = {
            "summary": {
                "total": len(results),
                "succeeded": len(results) - failed,
                "failed": failed,
            },
            "results": results,
        }
        response = json.dumps(payload)
        if failed:
            raise ToolError(response)
        return response


def programme_tools() -> tuple[ToolProtocol, ...]:
    return (
        OrganizerListSpacesTool(),
        OrganizerListTimeSlotsTool(),
        OrganizerListTracksTool(),
        OrganizerListProposalCategoriesTool(),
        OrganizerListSessionsTool(),
        OrganizerListFacilitatorsTool(),
        OrganizerCreateSpaceTool(),
        OrganizerCreateTimeSlotTool(),
        OrganizerCreateTrackTool(),
        OrganizerCreateProposalCategoryTool(),
        OrganizerFindOrCreateFacilitatorTool(),
        OrganizerCreateSessionTool(),
        OrganizerCreateSessionsTool(),
        OrganizerAssignSessionTool(),
        OrganizerAssignSessionsTool(),
    )
