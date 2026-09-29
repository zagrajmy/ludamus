"""What an event *is*, as opposed to the programme inside it.

The event's own settings — name, dates, the windows, the display switches —
beside `sphere_tools` for the sphere's. `programme_tools` holds what goes in
the event. Every field is optional and omitting one keeps it, so a caller
sends only what they mean to change.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from ludamus.gates.mcp.inputs import (
    SLUG_MAX_LENGTH,
    ImageUploadInput,
    NonBlankName,
    require_aware_datetime,
    validate_slug,
)
from ludamus.gates.mcp.organizer_context import actor_sphere, token_event
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.gates.uploads import validate_uploaded_logo, validate_uploaded_raster
from ludamus.pacts.event import EventDatesInvalidError, EventPublicationInvalidError
from ludamus.pacts.event_settings import EventSlugTakenError
from ludamus.pacts.mcp import ToolScope

# What `Event.address` holds.
ADDRESS_MAX_LENGTH = 255

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.legacy import EventUpdateData
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol


# Every setting is optional, and what the caller actually sent is what
# Pydantic already recorded in `model_fields_set` — so omitting a field means
# "leave it" without a flag saying so. That leaves `null` free to mean the one
# thing it means in the database: on a setting that is nullable there, an
# explicit null clears it; on one that is not, it reads as "no change", the
# same as leaving the field out.
class _UpdateEventInput(BaseModel):
    name: NonBlankName | None = Field(
        default=None, description="New event name; omit to keep"
    )
    slug: str | None = Field(
        default=None,
        max_length=SLUG_MAX_LENGTH,
        description=(
            "New URL slug; omit to keep. Every link already shared for this "
            "event stops working, so change it only on purpose."
        ),
    )
    description: str | None = Field(
        default=None, description="New event description; omit to keep the current one"
    )
    address: str | None = Field(
        default=None,
        max_length=ADDRESS_MAX_LENGTH,
        description="New venue address; omit to keep",
    )
    start_time: datetime | None = Field(
        default=None, description="New aware start time; omit to keep"
    )
    end_time: datetime | None = Field(
        default=None, description="New aware end time; omit to keep"
    )
    publication_time: datetime | None = Field(
        default=None,
        description=(
            "New aware publication time; null unsets it and hides the event; "
            "omit to keep"
        ),
    )
    proposal_start_time: datetime | None = Field(
        default=None,
        description=("New aware proposal-window start; null unsets it; omit to keep"),
    )
    proposal_end_time: datetime | None = Field(
        default=None,
        description="New aware proposal-window end; null unsets it; omit to keep",
    )
    allow_facilitator_session_edit: bool | None = Field(
        default=None,
        description=(
            "Whether facilitators may edit their own sessions here; null "
            "follows the sphere setting; omit to keep"
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

    @field_validator("slug")
    @classmethod
    def _routable_slug(cls, value: str | None) -> str | None:
        return None if value is None else validate_slug(value)

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


# Split by what a null means in the database, which is the only distinction
# between the two halves: one set of columns accepts it, the other does not.
def _event_settings_kept(body: _UpdateEventInput) -> EventUpdateData:
    """Collect the settings whose column rejects a null.

    Returns:
        The ones the caller sent to a value. Spelled out field by field rather
        than walked with getattr, so the TypedDict still checks each key.
    """
    sent = body.model_fields_set
    data: EventUpdateData = {}
    if "name" in sent and body.name is not None:
        data["name"] = body.name
    if "slug" in sent and body.slug is not None:
        data["slug"] = body.slug
    if "description" in sent and body.description is not None:
        data["description"] = body.description
    if "address" in sent and body.address is not None:
        data["address"] = body.address
    if "start_time" in sent and body.start_time is not None:
        data["start_time"] = body.start_time
    if "end_time" in sent and body.end_time is not None:
        data["end_time"] = body.end_time
    if "auto_confirm_sessions" in sent and body.auto_confirm_sessions is not None:
        data["auto_confirm_sessions"] = body.auto_confirm_sessions
    if (
        "use_session_cover_placeholders" in sent
        and body.use_session_cover_placeholders is not None
    ):
        data["use_session_cover_placeholders"] = body.use_session_cover_placeholders
    if "use_participants_label" in sent and body.use_participants_label is not None:
        data["use_participants_label"] = body.use_participants_label
    return data


def _event_settings_cleared(body: _UpdateEventInput) -> EventUpdateData:
    """Collect the settings whose column takes a null.

    Returns:
        The ones the caller sent, null included — that null is the clear.
    """
    sent = body.model_fields_set
    data: EventUpdateData = {}
    if "publication_time" in sent:
        data["publication_time"] = body.publication_time
    if "proposal_start_time" in sent:
        data["proposal_start_time"] = body.proposal_start_time
    if "proposal_end_time" in sent:
        data["proposal_end_time"] = body.proposal_end_time
    if "allow_facilitator_session_edit" in sent:
        data["allow_facilitator_session_edit"] = body.allow_facilitator_session_edit
    return data


def _event_update_data(body: _UpdateEventInput) -> EventUpdateData:
    """Turn the sent settings into one write shape.

    Returns:
        The union of the two halves, which never overlap.
    """
    return {**_event_settings_kept(body), **_event_settings_cleared(body)}


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
        # The same three refusals `create_event` gives, in the same words: a
        # caller should not have to learn a second vocabulary to edit what it
        # just made.
        try:
            return _apply_event_update(
                services=call.services, actor=call.actor, data=data
            )
        except EventDatesInvalidError as error:
            raise ToolError("end_time must be after start_time") from error
        except EventPublicationInvalidError as error:
            raise ToolError("publication_time must not be after start_time") from error
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


def event_tools() -> tuple[ToolProtocol, ...]:
    return (OrganizerUpdateEventTool(), OrganizerSetEventImageTool())
