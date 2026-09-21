"""Sphere and event settings over MCP.

The configuration half of the organizer toolset: what a sphere or an event
*is*, rather than the programme inside it (`programme_tools`). Every field is
optional and omitting one keeps it, so a caller can send only what they mean
to change.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from ludamus.gates.mcp.inputs import ImageUploadInput, require_aware_datetime
from ludamus.gates.mcp.organizer_context import actor_sphere, token_event
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.gates.uploads import validate_uploaded_logo, validate_uploaded_raster
from ludamus.pacts.event_settings import EventSlugTakenError
from ludamus.pacts.legacy import EncountersPolicy, EventUpdateData
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import SphereSettingsOutcome

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol


# Every event setting is optional and omitting one keeps it, so a caller can
# send the one thing they mean to change. `None` therefore cannot double as
# "clear this": the two timestamps that are genuinely nullable take an explicit
# clear_* flag, and the tri-state inheritance flag takes a word rather than a
# bool.
class _UpdateEventInput(BaseModel):
    name: str | None = Field(default=None, description="New event name; omit to keep")
    slug: str | None = Field(
        default=None,
        description=(
            "New URL slug; omit to keep. Every link already shared for this "
            "event stops working, so change it only on purpose."
        ),
    )
    description: str | None = Field(
        default=None, description="New event description; omit to keep the current one"
    )
    address: str | None = Field(
        default=None, description="New venue address; omit to keep"
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
    proposal_start_time: datetime | None = Field(
        default=None, description="New aware proposal-window start; omit to keep"
    )
    proposal_end_time: datetime | None = Field(
        default=None, description="New aware proposal-window end; omit to keep"
    )
    clear_proposal_window: bool = Field(
        default=False, description="Unset both proposal times (closes proposals)"
    )
    facilitator_session_edit: Literal["allow", "disallow", "inherit"] | None = Field(
        default=None,
        description=(
            "Whether facilitators may edit their own sessions here. 'inherit' "
            "follows the sphere setting; omit to keep the current choice."
        ),
    )
    auto_confirm_sessions: bool | None = Field(
        default=None,
        description=(
            "Confirm a programme item as soon as it is scheduled; omit to keep"
        ),
    )
    use_session_cover_placeholders: bool | None = Field(
        default=None,
        description="Draw a placeholder cover for sessions without one; omit to keep",
    )
    use_participants_label: bool | None = Field(
        default=None,
        description=(
            "Label the enrolled count 'Participants' instead of 'Players'; "
            "omit to keep"
        ),
    )

    @field_validator(
        "start_time",
        "end_time",
        "publication_time",
        "proposal_start_time",
        "proposal_end_time",
    )
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware_datetime(value)


class _SetEventImageInput(ImageUploadInput):
    kind: Literal["cover", "logo"] = Field(
        description=(
            "cover: the event cover image (raster only, 1920×1080 16:9 works "
            "best). logo: the printable-schedule logo (SVG allowed)."
        )
    )


def _apply_event_update(
    *, services: ServicesProtocol, actor: ActorContext, data: EventUpdateData
) -> str:
    event = token_event(services=services, actor=actor)
    services.event_settings.update_general(
        sphere_id=actor_sphere(actor), slug=event.slug, data=data
    )
    return token_event(services=services, actor=actor).model_dump_json(indent=2)


_FACILITATOR_EDIT: dict[str, bool | None] = {
    "allow": True,
    "disallow": False,
    "inherit": None,
}


def _plain_event_fields(body: _UpdateEventInput) -> EventUpdateData:
    """Collect the fields that carry over as sent.

    Returns:
        Only the ones set. Spelled out rather than walked with getattr so the
        TypedDict still type-checks each key.
    """
    data: EventUpdateData = {}
    if body.name is not None:
        data["name"] = body.name
    if body.slug is not None:
        data["slug"] = body.slug
    if body.description is not None:
        data["description"] = body.description
    if body.address is not None:
        data["address"] = body.address
    if body.start_time is not None:
        data["start_time"] = body.start_time
    if body.end_time is not None:
        data["end_time"] = body.end_time
    return data


def _event_flags(body: _UpdateEventInput) -> EventUpdateData:
    """Collect the programme switches, inheritance included.

    Returns:
        Only the ones set. `facilitator_session_edit` becomes the stored
        tri-state, where None means "follow the sphere".
    """
    data: EventUpdateData = {}
    if body.auto_confirm_sessions is not None:
        data["auto_confirm_sessions"] = body.auto_confirm_sessions
    if body.use_session_cover_placeholders is not None:
        data["use_session_cover_placeholders"] = body.use_session_cover_placeholders
    if body.use_participants_label is not None:
        data["use_participants_label"] = body.use_participants_label
    if body.facilitator_session_edit is not None:
        data["allow_facilitator_session_edit"] = _FACILITATOR_EDIT[
            body.facilitator_session_edit
        ]
    return data


def _event_windows(body: _UpdateEventInput) -> EventUpdateData:
    """Collect the two nullable time windows.

    Returns:
        Only what the caller set. These are the fields where None is a real
        stored value, so clearing one takes its own flag rather than an
        omitted field.
    """
    data: EventUpdateData = {}
    if body.clear_publication_time:
        data["publication_time"] = None
    elif body.publication_time is not None:
        data["publication_time"] = body.publication_time
    if body.clear_proposal_window:
        data["proposal_start_time"] = None
        data["proposal_end_time"] = None
        return data
    if body.proposal_start_time is not None:
        data["proposal_start_time"] = body.proposal_start_time
    if body.proposal_end_time is not None:
        data["proposal_end_time"] = body.proposal_end_time
    return data


def _event_update_data(body: _UpdateEventInput) -> EventUpdateData:
    """Turn the sent fields into one write shape.

    Returns:
        The union of the three groups, which never overlap.
    """
    return {**_plain_event_fields(body), **_event_flags(body), **_event_windows(body)}


class OrganizerUpdateEventTool(Tool[_UpdateEventInput]):
    name = "update_event"
    description = (
        "Update any of the token event's settings: name, slug, description, "
        "address, start/end times, publication and proposal windows, and the "
        "programme flags. Only provided fields change. Images have their own "
        "tool (set_event_image)."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateEventInput

    @staticmethod
    def handle(call: ToolCall[_UpdateEventInput]) -> str:
        if not (data := _event_update_data(call.data)):
            raise ToolError("Provide at least one field to update")
        try:
            return _apply_event_update(
                services=call.services, actor=call.actor, data=data
            )
        except EventSlugTakenError as error:
            message = (
                f"Another event in this sphere already uses the slug "
                f"{call.data.slug!r}."
            )
            raise ToolError(message) from error


class OrganizerSetEventImageTool(Tool[_SetEventImageInput]):
    name = "set_event_image"
    description = "Replace the token event's cover image or printable logo."
    scope = ToolScope.ORGANIZER
    input_model = _SetEventImageInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[_SetEventImageInput]) -> str:
        if call.data.kind == "cover":
            upload = call.data.validated_upload(validate_uploaded_raster)
            data: EventUpdateData = {"cover_image": upload}
        else:
            upload = call.data.validated_upload(validate_uploaded_logo)
            data = {"logo": upload}
        return _apply_event_update(services=call.services, actor=call.actor, data=data)


class OrganizerSetSphereLogoTool(Tool[ImageUploadInput]):
    name = "set_sphere_logo"
    description = "Replace the sphere's logo (SVG allowed)."
    scope = ToolScope.ORGANIZER
    input_model = ImageUploadInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[ImageUploadInput]) -> str:
        sphere_id = actor_sphere(call.actor)
        # Only the logo: naming the other settings here would hand back
        # whatever they read as, overwriting a change made in between.
        call.services.sphere_panel.update_settings(
            sphere_id, logo=call.data.validated_upload(validate_uploaded_logo)
        )
        return call.services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


class _UpdateSphereInput(BaseModel):
    facilitator_session_edit: bool | None = Field(
        default=None,
        description=(
            "Whether facilitators may edit their own sessions, for every event "
            "that does not override it; omit to keep"
        ),
    )
    encounters_policy: Literal["none", "managers", "everyone"] | None = Field(
        default=None,
        description=(
            "Who may create encounters here. 'none' turns the feature off and "
            "hides the ones that exist; omit to keep."
        ),
    )
    confirm_hiding_encounters: bool = Field(
        default=False,
        description=(
            "Required to set encounters_policy to 'none' while the sphere "
            "still has encounters. Without it nothing is written."
        ),
    )


class OrganizerUpdateSphereTool(Tool[_UpdateSphereInput]):
    name = "update_sphere"
    description = (
        "Update your sphere's settings: who may create encounters, and whether "
        "facilitators may edit their own sessions. Only provided fields "
        "change. The logo has its own tool (set_sphere_logo)."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateSphereInput

    @staticmethod
    def handle(call: ToolCall[_UpdateSphereInput]) -> str:
        if call.data.facilitator_session_edit is None and (
            call.data.encounters_policy is None
        ):
            raise ToolError("Provide at least one field to update")
        sphere_id = actor_sphere(call.actor)
        # Straight through: an omitted field stays omitted all the way to the
        # UPDATE, so a setting this call never mentions is never rewritten.
        outcome = call.services.sphere_panel.update_settings(
            sphere_id,
            allow_facilitator_session_edit=call.data.facilitator_session_edit,
            encounters_policy=(
                EncountersPolicy(call.data.encounters_policy)
                if call.data.encounters_policy is not None
                else None
            ),
            confirmed_encounters_disable=call.data.confirm_hiding_encounters,
        )
        if outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION:
            raise ToolError(
                "This sphere still has encounters, and 'none' hides them. "
                "Repeat the call with confirm_hiding_encounters=true to go "
                "ahead."
            )
        return call.services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


def settings_tools() -> tuple[ToolProtocol, ...]:
    return (
        OrganizerUpdateEventTool(),
        OrganizerSetEventImageTool(),
        OrganizerSetSphereLogoTool(),
        OrganizerUpdateSphereTool(),
    )
