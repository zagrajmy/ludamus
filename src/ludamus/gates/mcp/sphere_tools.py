from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from ludamus.gates.mcp.inputs import ImageUploadInput
from ludamus.gates.mcp.organizer_context import actor_sphere
from ludamus.gates.mcp.registry import Tool, ToolCall
from ludamus.gates.uploads import validate_uploaded_logo
from ludamus.pacts.legacy import EncounterPublicPolicy, SpherePage
from ludamus.pacts.mcp import ToolScope

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
    enabled_pages: list[SpherePage] | None = Field(
        default=None, min_length=1, description="Sphere pages that remain enabled"
    )
    default_page: SpherePage | None = Field(
        default=None,
        description="Page shown at the sphere root; it must also be enabled",
    )
    encounter_public_policy: EncounterPublicPolicy | None = Field(
        default=None, description="Who may see public encounter listings"
    )

    @model_validator(mode="before")
    @classmethod
    def validate_patch(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        if not data:
            raise ValueError("Provide at least one sphere setting to update")
        if any(value is None for value in data.values()):
            raise ValueError("Omit unchanged settings instead of passing null")
        return data

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
        if self.enabled_pages is not None:
            changes["enabled_pages"] = self.enabled_pages
        if self.default_page is not None:
            changes["default_page"] = self.default_page
        if self.encounter_public_policy is not None:
            changes["encounter_public_policy"] = self.encounter_public_policy
        return changes


class OrganizerUpdateSphereSettingsTool(Tool[_UpdateSphereSettingsInput]):
    name = "update_sphere_settings"
    description = "Patch one or more settings for the token's sphere."
    scope = ToolScope.ORGANIZER
    input_model = _UpdateSphereSettingsInput

    @staticmethod
    def handle(call: ToolCall[_UpdateSphereSettingsInput]) -> str:
        sphere_id = actor_sphere(call.actor)
        call.services.sphere_panel.patch_settings(
            sphere_id, changes=call.data.to_patch()
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
