"""Contracts for the Konwencik agenda export."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        AgendaItemRepositoryProtocol,
        EventRepositoryProtocol,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionRepositoryProtocol,
        SpaceRepositoryProtocol,
        TrackRepositoryProtocol,
    )


@dataclass(frozen=True)
class KonwencikScheduleRepos:
    """Everything the export reads an event's program out of."""

    agenda_items: AgendaItemRepositoryProtocol
    spaces: SpaceRepositoryProtocol
    tracks: TrackRepositoryProtocol
    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    events: EventRepositoryProtocol
    categories: ProposalCategoryRepositoryProtocol


class KonwencikSheetConfig(BaseModel):
    spreadsheet_id: str
    # Konwencik creates the tab under this name; the field exists so a rename
    # is a config edit rather than a code change.
    tab: str = "harmonogram"


class KonwencikExportSettings(BaseModel):
    # Keyed on pk throughout: slugs are re-derived whenever a track, category
    # or session field is renamed, so a slug key would silently orphan.
    category_icons: dict[int, str] = {}  # ProposalCategory pk -> "fa.gamepad"
    track_colors: dict[int, str] = {}  # Track pk -> "#rrggbb"
    photo_url_field_pk: int | None = None  # SessionField pk
    icon_field_pk: int | None = None


class KonwencikExportOutcome(BaseModel):
    rows_written: int
    sessions_skipped: int


class KonwencikNamedItemDTO(BaseModel):
    """A category, track or session field the settings page offers a row for."""

    pk: int
    name: str


class KonwencikSettingsContext(BaseModel):
    display_name: str
    categories: list[KonwencikNamedItemDTO]
    tracks: list[KonwencikNamedItemDTO]
    session_fields: list[KonwencikNamedItemDTO]
    settings: KonwencikExportSettings


class KonwencikExportServiceProtocol(Protocol):
    def export_now(
        self, *, sphere_id: int, event_pk: int, pk: int
    ) -> KonwencikExportOutcome: ...
    def get_settings_context(
        self, *, sphere_id: int, event_pk: int, pk: int
    ) -> KonwencikSettingsContext: ...
    def save_settings(
        self,
        *,
        sphere_id: int,
        event_pk: int,
        pk: int,
        settings: KonwencikExportSettings,
    ) -> None: ...
