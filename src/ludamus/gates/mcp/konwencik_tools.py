"""Organizer tools for Konwencik's category icons and track backgrounds."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from ludamus.gates.mcp.inputs import EmptyInput
from ludamus.gates.mcp.organizer_context import token_event
from ludamus.gates.mcp.registry import Tool, ToolCall
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import KonwencikSettingsContext
from ludamus.pacts.mcp import ToolScope


class _IntegrationSettings(BaseModel):
    integration_id: int
    context: KonwencikSettingsContext


_SETTINGS_LIST = TypeAdapter(list[_IntegrationSettings])


class _UpdateStylesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: int = Field(
        description="Integration id from get_konwencik_settings"
    )
    track_colors: dict[
        int, Annotated[str, StringConstraints(pattern=r"^(#[0-9a-fA-F]{6})?$")]
    ] = Field(
        default_factory=dict, description="Track pk to #rrggbb; empty string clears"
    )
    category_icons: dict[
        int, Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
    ] = Field(
        default_factory=dict,
        description="Category pk to fa.gamepad; empty string clears",
    )


class OrganizerGetKonwencikSettingsTool(Tool[EmptyInput]):
    name = "get_konwencik_settings"
    description = (
        "Read this token's event's Konwencik integrations and settings, with track, "
        "category and session-field IDs/names. Empty list means none configured. "
        "Does not return connection credentials or export anything."
    )
    scope = ToolScope.ORGANIZER
    input_model = EmptyInput

    @staticmethod
    def handle(call: ToolCall[EmptyInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        return _SETTINGS_LIST.dump_json(
            [
                _IntegrationSettings(
                    integration_id=integration.pk,
                    context=call.services.konwencik_export.get_settings_context(
                        sphere_id=event.sphere_id, event_pk=event.pk, pk=integration.pk
                    ),
                )
                for integration in call.services.event_integrations.list_for_event(
                    event.pk, IntegrationKind.EXPORT
                )
                if integration.implementation
                == IntegrationImplementationId.KONWENCIK_SHEET_PUSHER
            ],
            indent=2,
        ).decode()


class OrganizerUpdateKonwencikStylesTool(Tool[_UpdateStylesInput]):
    name = "update_konwencik_styles"
    description = (
        "Patch track colors and category icons for a Konwencik integration in this "
        "token's event. Omitted entries stay unchanged; empty strings remove an "
        "override. Other settings and export locks stay unchanged. Does not export; "
        "if automatic sync is enabled, the next sync uses these styles."
    )
    scope = ToolScope.ORGANIZER
    input_model = _UpdateStylesInput

    @staticmethod
    def handle(call: ToolCall[_UpdateStylesInput]) -> str:
        event = token_event(services=call.services, actor=call.actor)
        return call.services.konwencik_export.update_styles(
            sphere_id=event.sphere_id,
            event_pk=event.pk,
            pk=call.data.integration_id,
            track_colors=call.data.track_colors,
            category_icons=call.data.category_icons,
        ).model_dump_json(indent=2)
