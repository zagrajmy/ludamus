from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ludamus.gates.mcp.inputs import ImageUploadInput
from ludamus.gates.mcp.organizer_context import actor_sphere
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError
from ludamus.gates.uploads import validate_uploaded_logo
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.mcp import ToolScope
from ludamus.pacts.multiverse import SphereSettingsOutcome, SphereVisibility

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolProtocol
    from ludamus.pacts.multiverse import SphereSettingsPatch


class _UpdateSphereSettingsInput(BaseModel):
    allow_facilitator_session_edit: bool | None = Field(
        default=None,
        description="Whether facilitators may edit their accepted sessions",
    )
    event_cover_buttons_at_bottom: bool | None = Field(
        default=None,
        description=(
            "True places event-cover buttons in a horizontal row at the bottom "
            "right; false restores the default top-right position"
        ),
    )
    visibility: SphereVisibility | None = Field(
        default=None,
        description=(
            "public: suggested on the Zagrajmy landing and dashboard; "
            "unlisted: open to anyone with the link, never suggested; "
            "private: open only to the sphere's members"
        ),
    )
    encounters_policy: EncountersPolicy | None = Field(
        default=None, description="Who may organize encounters in the sphere"
    )
    confirmed_encounters_disable: bool = Field(
        default=False,
        description=(
            "Confirm hiding existing encounters when setting encounters_policy to none"
        ),
    )

    def to_patch(self) -> SphereSettingsPatch:
        changes: SphereSettingsPatch = {}
        if self.allow_facilitator_session_edit is not None:
            changes["allow_facilitator_session_edit"] = (
                self.allow_facilitator_session_edit
            )
        if self.event_cover_buttons_at_bottom is not None:
            changes["event_cover_buttons_at_bottom"] = (
                self.event_cover_buttons_at_bottom
            )
        if self.visibility is not None:
            changes["visibility"] = self.visibility
        if self.encounters_policy is not None:
            changes["encounters_policy"] = self.encounters_policy
        return changes


class OrganizerUpdateSphereSettingsTool(Tool[_UpdateSphereSettingsInput]):
    name = "update_sphere_settings"
    description = "Patch one or more settings for the token's sphere."
    scope = ToolScope.ORGANIZER
    input_model = _UpdateSphereSettingsInput

    @staticmethod
    def handle(call: ToolCall[_UpdateSphereSettingsInput]) -> str:
        provided = call.data.model_fields_set - {"confirmed_encounters_disable"}
        if not provided:
            raise ToolError("Provide at least one sphere setting to update")
        has_explicit_null = (
            (
                "allow_facilitator_session_edit" in provided
                and call.data.allow_facilitator_session_edit is None
            )
            or (
                "event_cover_buttons_at_bottom" in provided
                and call.data.event_cover_buttons_at_bottom is None
            )
            or ("visibility" in provided and call.data.visibility is None)
            or ("encounters_policy" in provided and call.data.encounters_policy is None)
        )
        if has_explicit_null:
            raise ToolError("Omit unchanged settings instead of passing null")

        sphere_id = actor_sphere(call.actor)
        outcome = call.services.sphere_panel.patch_settings(
            sphere_id,
            changes=call.data.to_patch(),
            confirmed_encounters_disable=call.data.confirmed_encounters_disable,
        )
        if outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION:
            raise ToolError(
                "This sphere has encounters. Retry with "
                "confirmed_encounters_disable=true to hide them."
            )
        return call.services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


class OrganizerSetSphereLogoTool(Tool[ImageUploadInput]):
    name = "set_sphere_logo"
    description = "Replace the sphere's logo (SVG allowed)."
    scope = ToolScope.ORGANIZER
    input_model = ImageUploadInput
    audit_redacted_keys = frozenset({"content_base64"})

    @staticmethod
    def handle(call: ToolCall[ImageUploadInput]) -> str:
        sphere_id = actor_sphere(call.actor)
        upload = call.data.validated_upload(validate_uploaded_logo)
        call.services.sphere_panel.update_logo(sphere_id, upload)
        return call.services.sphere_panel.read(sphere_id).model_dump_json(indent=2)


def sphere_tools() -> tuple[ToolProtocol, ...]:
    return (OrganizerUpdateSphereSettingsTool(), OrganizerSetSphereLogoTool())
