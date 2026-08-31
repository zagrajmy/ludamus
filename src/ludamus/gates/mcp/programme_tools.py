from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from django.core.files.base import ContentFile
from django.utils.text import slugify
from pydantic import BaseModel, Field, TypeAdapter, field_validator

from ludamus.gates.mcp.inputs import (
    AwareDatetimeRange,
    EmptyInput,
    NonBlankName,
    require_aware_datetime,
)
from ludamus.gates.mcp.organizer_context import actor_sphere, token_event
from ludamus.gates.mcp.protocol import JsonDict
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import SessionPlacement
from ludamus.pacts.durations import normalize_duration
from ludamus.pacts.event import FacilitatorListItemDTO, TimeSlotRejectedError
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
    SourceRowIdMissingError,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import AccreditationType
from ludamus.pacts.timetable import PlacementRejectedError
from ludamus.pacts.tracks import TrackSelectionInvalidError
from ludamus.pacts.venues import SpaceInputDTO, SpaceTreeNodeDTO, SpaceValidationError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.legacy import EventUpdateData
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

_PROPOSAL_CATEGORY_LIST = TypeAdapter(list[ProposalCategoryDTO])
_SPACE_LEAF_LIST = TypeAdapter(list["_SpaceLeaf"])
_TIME_SLOT_LIST = TypeAdapter(list[TimeSlotDTO])
_SESSION_LIST = TypeAdapter(list[SessionListItemDTO])
_FACILITATOR_LIST = TypeAdapter(list[FacilitatorListItemDTO])
_TRACK_LIST = TypeAdapter(list["_TrackListItem"])
_JSON_OBJECT: TypeAdapter[JsonDict] = TypeAdapter(JsonDict)


class _EventIdInput(BaseModel):
    event_id: int = Field(description="Event primary key (see list_events / get_event)")


class _ListSpacesInput(_EventIdInput):
    include_internal: bool = Field(
        default=False,
        description="Include venue and area nodes, not only assignable leaves",
    )


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


def _flatten_spaces(
    nodes: list[SpaceTreeNodeDTO], *, include_internal: bool, prefix: str = ""
) -> list[_SpaceLeaf]:
    spaces: list[_SpaceLeaf] = []
    for node in nodes:
        path = f"{prefix} > {node.space.name}" if prefix else node.space.name
        if include_internal or node.is_leaf:
            spaces.append(
                _SpaceLeaf(
                    pk=node.space.pk,
                    name=node.space.name,
                    path=path,
                    capacity=node.space.capacity,
                    parent_id=node.space.parent_id,
                )
            )
        spaces.extend(
            _flatten_spaces(
                node.children, include_internal=include_internal, prefix=path
            )
        )
    return spaces


class OrganizerCurrentEventTool(Tool[EmptyInput]):
    name = "get_current_event"
    description = "Get the event this organizer token can write to."
    scope = ToolScope.ORGANIZER
    input_model = EmptyInput

    @staticmethod
    def handle(call: ToolCall[EmptyInput]) -> str:
        return token_event(services=call.services, actor=call.actor).model_dump_json(
            indent=2
        )


class OrganizerListSpacesTool(Tool[_ListSpacesInput]):
    name = "list_spaces"
    description = (
        "List spaces for an event, with path labels through the venue/area tree. "
        "Returns assignable leaves unless include_internal is true."
    )
    scope = ToolScope.ORGANIZER
    input_model = _ListSpacesInput

    @staticmethod
    def handle(call: ToolCall[_ListSpacesInput]) -> str:
        event = _require_event(call)
        spaces = _flatten_spaces(
            call.services.space_tree.list_tree(event.pk),
            include_internal=call.data.include_internal,
        )
        return _SPACE_LEAF_LIST.dump_json(spaces, indent=2).decode()


class OrganizerListTimeSlotsTool(Tool[_EventIdInput]):
    name = "list_time_slots"
    description = "List time slots (day windows) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        slots = call.services.panel_time_slots.list_for_event(event.pk)
        return _TIME_SLOT_LIST.dump_json(slots, indent=2).decode()


class _TrackListItem(TrackListItemDTO):
    space_ids: list[int]


class OrganizerListTracksTool(Tool[_EventIdInput]):
    name = "list_tracks"
    description = "List programme tracks (bloki) for an event."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event_pk = _require_event(call).pk
        space_pks = call.services.tracks_panel.list_space_pks_by_event(event_pk)
        tracks = [
            _TrackListItem(
                pk=track.pk,
                name=track.name,
                slug=track.slug,
                is_public=track.is_public,
                space_names=track.space_names,
                manager_names=track.manager_names,
                space_ids=space_pks.get(track.pk, []),
            )
            for track in call.services.tracks_panel.list_tracks(event_pk)
        ]
        return _TRACK_LIST.dump_json(tracks, indent=2).decode()


class OrganizerListProposalCategoriesTool(Tool[_EventIdInput]):
    name = "list_proposal_categories"
    description = "List proposal categories for an event in this token's sphere."
    scope = ToolScope.ORGANIZER
    input_model = _EventIdInput

    @staticmethod
    def handle(call: ToolCall[_EventIdInput]) -> str:
        event = _require_event(call)
        context = call.services.proposal_categories.get_page_context(event.pk)
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
        return _SESSION_LIST.dump_json(context.proposals, indent=2).decode()


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
        return _FACILITATOR_LIST.dump_json(context.facilitators, indent=2).decode()


class _CreateSpaceInput(BaseModel):
    name: NonBlankName
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


class OrganizerCreateTimeSlotTool(Tool[AwareDatetimeRange]):
    name = "create_time_slot"
    description = "Create a day time-slot window for this token's event."
    scope = ToolScope.ORGANIZER
    input_model = AwareDatetimeRange

    @staticmethod
    def handle(call: ToolCall[AwareDatetimeRange]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        try:
            created = call.services.panel_time_slots.create(
                event=event,
                start_time=call.data.start_time,
                end_time=call.data.end_time,
            )
        except TimeSlotRejectedError as error:
            raise ToolError(str(error)) from error
        return created.model_dump_json(indent=2)


class _CreateTrackInput(BaseModel):
    name: NonBlankName
    is_public: bool = True
    space_ids: list[int] = Field(default_factory=list)
    manager_ids: list[int] = Field(default_factory=list)


class OrganizerCreateTrackTool(Tool[_CreateTrackInput]):
    name = "create_track"
    description = (
        "Create a programme track (blok) for this token's event, or return the "
        "one that already carries this name. Names identify a track, so a "
        "repeated import never adds a second copy."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateTrackInput

    @staticmethod
    def handle(call: ToolCall[_CreateTrackInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        try:
            created = call.services.tracks_panel.find_or_create(
                event_pk=event.pk,
                sphere_id=actor_sphere(call.actor),
                data={
                    "name": call.data.name,
                    "is_public": call.data.is_public,
                    "space_pks": call.data.space_ids,
                    "manager_pks": call.data.manager_ids,
                },
            )
        except TrackSelectionInvalidError as error:
            message = (
                "space_ids must belong to this event and manager_ids to its sphere"
            )
            raise ToolError(message) from error
        return created.model_dump_json(indent=2)


class _CreateProposalCategoryInput(BaseModel):
    name: NonBlankName


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
    display_name: NonBlankName


class OrganizerFindOrCreateFacilitatorTool(Tool[_FindOrCreateFacilitatorInput]):
    name = "find_or_create_facilitator"
    description = (
        "Find a facilitator by exact display name in this token's event, or create one."
    )
    scope = ToolScope.ORGANIZER
    input_model = _FindOrCreateFacilitatorInput
    audit_redacted_keys = frozenset({"display_name"})

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


def _batch_audit_arguments(
    arguments: JsonDict, *, key: str, count_key: str, item_key: str
) -> JsonDict:
    items = arguments.get(key)
    if not isinstance(items, list):
        return {key: "[redacted]"}
    return {
        count_key: len(items),
        f"{item_key}s": [
            item.get(item_key) for item in items if isinstance(item, dict)
        ],
    }


def _batch_response[T](
    items: Sequence[T],
    *,
    key_name: str,
    key_of: Callable[[T], str | int],
    payload_key: str,
    run: Callable[[T], str],
) -> str:
    results: list[JsonDict] = []
    failed = 0
    for index, item in enumerate(items):
        entry: JsonDict = {"index": index, key_name: key_of(item)}
        try:
            item_json = run(item)
        except (NotFoundError, ToolError) as error:
            failed += 1
            reason = "Resource not found" if isinstance(error, NotFoundError) else error
            entry |= {"status": "failed", "error": str(reason)}
        else:
            entry |= {
                "status": "ok",
                payload_key: _JSON_OBJECT.validate_json(item_json),
            }
        results.append(entry)
    summary: JsonDict = {
        "total": len(results),
        "succeeded": len(results) - failed,
        "failed": failed,
    }
    body: JsonDict = {"summary": summary, "results": results}
    response = json.dumps(body)
    if failed:
        raise ToolError(response)
    return response


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

    title: NonBlankName
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
    except SourceRowIdMissingError as error:
        raise ToolError("source_row_id must be non-empty") from error
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
    audit_redacted_keys = frozenset({"display_name", "description"})

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

    @classmethod
    def audit_arguments(cls, arguments: JsonDict) -> object:
        return _batch_audit_arguments(
            arguments,
            key="sessions",
            count_key="session_count",
            item_key="source_row_id",
        )

    @staticmethod
    def handle(call: ToolCall[_CreateSessionsInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        return _batch_response(
            call.data.sessions,
            key_name="source_row_id",
            key_of=lambda session: session.source_row_id,
            payload_key="session",
            run=lambda session: _create_session(
                services=call.services, event=event, data=session
            ),
        )


class _AssignSessionInput(AwareDatetimeRange):
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
    placement: JsonDict = {"session_id": data.session_id, "space_id": data.space_id}
    return json.dumps(placement)


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

    @classmethod
    def audit_arguments(cls, arguments: JsonDict) -> object:
        return _batch_audit_arguments(
            arguments,
            key="assignments",
            count_key="assignment_count",
            item_key="session_id",
        )

    @staticmethod
    def handle(call: ToolCall[_AssignSessionsInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        return _batch_response(
            call.data.assignments,
            key_name="session_id",
            key_of=lambda assignment: assignment.session_id,
            payload_key="assignment",
            run=lambda assignment: _assign_session(
                services=call.services, actor=call.actor, event=event, data=assignment
            ),
        )


MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024


class _UpdateEventInput(BaseModel):
    description: str | None = Field(
        default=None, description="New event description; omit to keep the current one"
    )
    start_time: datetime | None = Field(
        default=None, description="New aware start time; omit to keep"
    )
    end_time: datetime | None = Field(
        default=None, description="New aware end time; omit to keep"
    )
    publication_time: datetime | None = Field(
        default=None, description="New aware publication time; omit to keep"
    )
    clear_publication_time: bool = Field(
        default=False, description="Unset the publication time (hides the event)"
    )

    @field_validator("start_time", "end_time", "publication_time")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware_datetime(value)


class _ImageUploadInput(BaseModel):
    filename: NonBlankName = Field(description="Original file name, with extension")
    content_base64: str = Field(
        description=(
            "File content, standard base64. Decoded size is capped at 5 MB, and "
            "the HTTP body cap applies to the whole request."
        )
    )

    def decoded_content(self) -> bytes:
        try:
            content = base64.b64decode(self.content_base64, validate=True)
        except binascii.Error as error:
            message = f"content_base64 is not valid base64: {error}"
            raise ToolError(message) from error
        if len(content) > MAX_IMAGE_UPLOAD_BYTES:
            message = "Decoded content exceeds the 5 MB upload cap"
            raise ToolError(message)
        if not content:
            raise ToolError("content_base64 decoded to an empty file")
        return content


class _SetEventImageInput(_ImageUploadInput):
    kind: Literal["cover", "logo"] = Field(
        description=(
            "cover: the event cover image (raster only, 1920×1080 16:9 works "
            "best). logo: the printable-schedule logo (SVG allowed)."
        )
    )


class _UpdateSpaceInput(BaseModel):
    pk: int = Field(description="Space primary key (see list_spaces)")
    name: NonBlankName | None = Field(
        default=None, description="New name; omit to keep"
    )
    parent_id: int | Literal["root"] | None = Field(
        default=None,
        description=(
            'New parent space id, or "root" to move to the top level; '
            "omit to keep the current parent"
        ),
    )
    capacity: int | None = Field(default=None, description="New capacity; omit to keep")
    description: str | None = Field(
        default=None, description="New description; omit to keep"
    )
    location: str | None = Field(default=None, description="New location; omit to keep")


class OrganizerUpdateSpaceTool(Tool[_UpdateSpaceInput]):
    name = "update_space"
    description = (
        "Rename, move, or edit a space in this token's event venue tree. "
        "Only provided fields change; sessions assigned to the space stay put."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateSpaceInput

    @staticmethod
    def handle(call: ToolCall[_UpdateSpaceInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        current = call.services.space_tree.read(call.data.pk)
        if current.event_id != event.pk:
            raise NotFoundError
        if call.data.parent_id == "root":
            parent_id = None
        elif call.data.parent_id is None:
            parent_id = current.parent_id
        else:
            parent = call.services.space_tree.read(call.data.parent_id)
            if parent.event_id != event.pk:
                raise NotFoundError
            parent_id = parent.pk
        try:
            space = call.services.space_tree.update(
                pk=current.pk,
                parent_id=parent_id,
                data=SpaceInputDTO(
                    name=call.data.name or current.name,
                    capacity=(
                        current.capacity
                        if call.data.capacity is None
                        else call.data.capacity
                    ),
                    description=(
                        current.description
                        if call.data.description is None
                        else call.data.description
                    ),
                    location=(
                        current.location
                        if call.data.location is None
                        else call.data.location
                    ),
                ),
            )
        except SpaceValidationError as error:
            raise ToolError(str(error)) from error
        return space.model_dump_json(indent=2)


class OrganizerUpdateEventTool(Tool[_UpdateEventInput]):
    name = "update_event"
    description = (
        "Update the token event's description, start/end times, or publication "
        "time. Only provided fields change."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateEventInput

    @staticmethod
    def handle(call: ToolCall[_UpdateEventInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        data: EventUpdateData = {}
        if call.data.description is not None:
            data["description"] = call.data.description
        if call.data.start_time is not None:
            data["start_time"] = call.data.start_time
        if call.data.end_time is not None:
            data["end_time"] = call.data.end_time
        if call.data.clear_publication_time:
            data["publication_time"] = None
        elif call.data.publication_time is not None:
            data["publication_time"] = call.data.publication_time
        if not data:
            raise ToolError("Provide at least one field to update")
        call.services.event_settings.update_general(
            sphere_id=actor_sphere(call.actor), slug=event.slug, data=data
        )
        return token_event(services=call.services, actor=call.actor).model_dump_json(
            indent=2
        )


class OrganizerSetEventImageTool(Tool[_SetEventImageInput]):
    name = "set_event_image"
    description = "Replace the token event's cover image or printable logo."
    scope = ToolScope.ORGANIZER
    input_model = _SetEventImageInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[_SetEventImageInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        upload = ContentFile(call.data.decoded_content(), name=call.data.filename)
        field = "cover_image" if call.data.kind == "cover" else "logo"
        data = cast("EventUpdateData", {field: upload})
        call.services.event_settings.update_general(
            sphere_id=actor_sphere(call.actor), slug=event.slug, data=data
        )
        return token_event(services=call.services, actor=call.actor).model_dump_json(
            indent=2
        )


class OrganizerSetSphereLogoTool(Tool[_ImageUploadInput]):
    name = "set_sphere_logo"
    description = "Replace the sphere's logo (SVG allowed)."
    scope = ToolScope.ORGANIZER
    input_model = _ImageUploadInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[_ImageUploadInput]) -> str:
        sphere_id = actor_sphere(call.actor)
        sphere = call.services.sphere_panel.read(sphere_id)
        upload = ContentFile(call.data.decoded_content(), name=call.data.filename)
        call.services.sphere_panel.update_settings(
            sphere_id,
            allow_facilitator_session_edit=sphere.allow_facilitator_session_edit,
            enabled_pages=sphere.enabled_pages,
            default_page=sphere.default_page,
            encounter_public_policy=sphere.encounter_public_policy,
            logo=upload,
        )
        return call.services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


def programme_tools() -> tuple[ToolProtocol, ...]:
    return (
        OrganizerCurrentEventTool(),
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
        OrganizerUpdateSpaceTool(),
        OrganizerUpdateEventTool(),
        OrganizerSetEventImageTool(),
        OrganizerSetSphereLogoTool(),
    )
