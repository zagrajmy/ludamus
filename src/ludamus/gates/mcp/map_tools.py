"""Organizer MCP tools for an event's venue plans."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, TypeAdapter

from ludamus.gates.mcp.inputs import EventIdInput, ImageUploadInput, NonBlankName
from ludamus.gates.mcp.organizer_context import require_event, token_event
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.gates.uploads import validate_uploaded_raster
from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import EventMapDTO, EventMapRecordDTO
from ludamus.pacts.mcp import ToolScope

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.core.files.base import ContentFile

    from ludamus.gates.mcp.protocol import JsonDict
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

_EVENT_MAP_LIST = TypeAdapter(list[EventMapDTO])


class _MapIdInput(BaseModel):
    map_id: int = Field(description="Event map primary key (see list_maps)")


class _CreateMapInput(BaseModel):
    name: NonBlankName = Field(
        description="What the plan shows: a building, a floor, the whole site"
    )
    pages: list[ImageUploadInput] = Field(
        min_length=1,
        description=(
            "The plan's pictures in reading order. Several for a plan that comes "
            "with a legend; they render side by side."
        ),
    )


class _UpdateMapInput(_MapIdInput):
    name: NonBlankName = Field(description="New name for the plan")
    pages: list[ImageUploadInput] | None = Field(
        default=None,
        description="Replacement pictures for the whole plan; omit to keep them",
    )


class _SetMapSpacesInput(_MapIdInput):
    space_ids: list[int] = Field(
        description=(
            "Spaces this plan draws (see list_spaces with include_internal). "
            "Replaces the whole set; an empty list detaches everything."
        )
    )


def _validated_pages(pages: Sequence[ImageUploadInput]) -> list[ContentFile[bytes]]:
    return [page.validated_upload(validate_uploaded_raster) for page in pages]


def _map_in_token_event(
    *, services: ServicesProtocol, actor: ActorContext, map_id: int
) -> EventMapRecordDTO:
    event = token_event(services=services, actor=actor)
    try:
        return services.event_maps.read(event_pk=event.pk, pk=map_id)
    except NotFoundError as error:
        message = f"No map {map_id} in this token's event"
        raise ToolError(message) from error


class OrganizerListMapsTool(Tool[EventIdInput]):
    name = "list_maps"
    description = (
        "List an event's venue plans: pk, name, page image URLs, and the space "
        "pks each plan draws. Read-only; works for any event in this sphere."
    )
    scope = ToolScope.ORGANIZER
    input_model = EventIdInput

    @staticmethod
    def handle(call: ToolCall[EventIdInput]) -> str:
        event = require_event(
            services=call.services, actor=call.actor, event_id=call.data.event_id
        )
        maps = call.services.event_maps.list_for_event(event.pk)
        return _EVENT_MAP_LIST.dump_json(maps, indent=2).decode()


class OrganizerCreateMapTool(Tool[_CreateMapInput]):
    name = "create_map"
    description = (
        "Add a venue plan to this token's event from one or more uploaded "
        "pictures. Attach the spaces it draws with set_map_spaces."
    )
    scope = ToolScope.ORGANIZER
    input_model = _CreateMapInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[_CreateMapInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        event_map = call.services.event_maps.create(
            event_pk=event.pk,
            name=call.data.name,
            images=_validated_pages(call.data.pages),
        )
        return event_map.model_dump_json(indent=2)


class OrganizerUpdateMapTool(Tool[_UpdateMapInput]):
    name = "update_map"
    description = (
        "Rename a plan in this token's event, and optionally replace all of its "
        "pictures. The spaces it draws stay put."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateMapInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[_UpdateMapInput]) -> str:
        event_map = _map_in_token_event(
            services=call.services, actor=call.actor, map_id=call.data.map_id
        )
        updated = call.services.event_maps.update(
            event_pk=event_map.event_id,
            pk=event_map.pk,
            name=call.data.name,
            images=(
                None if call.data.pages is None else _validated_pages(call.data.pages)
            ),
        )
        return updated.model_dump_json(indent=2)


class OrganizerSetMapSpacesTool(Tool[_SetMapSpacesInput]):
    name = "set_map_spaces"
    description = (
        "Set which spaces a plan in this token's event draws. Each attached "
        "space is listed beside the plan and links to its sessions."
    )
    scope = ToolScope.ORGANIZER
    input_model = _SetMapSpacesInput

    @staticmethod
    def handle(call: ToolCall[_SetMapSpacesInput]) -> str:
        event_map = _map_in_token_event(
            services=call.services, actor=call.actor, map_id=call.data.map_id
        )
        try:
            call.services.event_maps.attach_spaces(
                event_pk=event_map.event_id,
                pk=event_map.pk,
                space_pks=call.data.space_ids,
            )
        except NotFoundError as error:
            raise ToolError("A space id does not belong to this event") from error
        return call.services.event_maps.read(
            event_pk=event_map.event_id, pk=event_map.pk
        ).model_dump_json(indent=2)


class OrganizerDeleteMapTool(Tool[_MapIdInput]):
    name = "delete_map"
    description = "Remove a plan from this token's event, pictures and all."
    scope = ToolScope.ORGANIZER
    input_model = _MapIdInput

    @staticmethod
    def handle(call: ToolCall[_MapIdInput]) -> str:
        event_map = _map_in_token_event(
            services=call.services, actor=call.actor, map_id=call.data.map_id
        )
        call.services.event_maps.delete(event_pk=event_map.event_id, pk=event_map.pk)
        result: JsonDict = {"deleted": event_map.pk, "name": event_map.name}
        return json.dumps(result, indent=2)


def map_tools() -> tuple[ToolProtocol, ...]:
    return (
        OrganizerListMapsTool(),
        OrganizerCreateMapTool(),
        OrganizerUpdateMapTool(),
        OrganizerSetMapSpacesTool(),
        OrganizerDeleteMapTool(),
    )
