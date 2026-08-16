# TODO(hasparus): Fold this module into pacts/event.py, and
# mills/event_settings.py into mills/event.py, in a follow-up. GLIMPSE slices
# pacts and mills by noun then verb, and `event_settings` is an entity cut of
# the `event` noun, not a verb; folded in, both files stay far below the
# ~1000-line threshold that would justify the split. The split existed only to
# keep this branch off files #726 and #728 were rewriting; both have merged, so
# neither fold target is contested any more and the move is now mechanical. It
# is left out of this PR to keep the diff a pure request.services migration.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.legacy import (
        EventProposalSettingsDTO,
        EventProposalSettingsRepositoryProtocol,
        EventRepositoryProtocol,
        EventSettingsRepositoryProtocol,
        EventUpdateData,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRepositoryProtocol,
    )


class EventSlugTakenError(Exception):
    pass


@dataclass
class EventSettingsRepos:
    events: EventRepositoryProtocol
    event_settings: EventSettingsRepositoryProtocol
    event_proposal_settings: EventProposalSettingsRepositoryProtocol
    proposal_categories: ProposalCategoryRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol


@dataclass
class EventDisplaySettingsContextDTO:
    fields: list[OrganizerFieldDTO]
    displayed_field_ids: list[int]


class ProposalSettingsUpdateData(TypedDict):
    description: str
    proposal_start_time: datetime | None
    proposal_end_time: datetime | None
    allow_anonymous_proposals: bool
    apply_dates_to_categories: bool


class EventSettingsServiceProtocol(Protocol):
    def update_general(
        self, *, sphere_id: int, slug: str, data: EventUpdateData
    ) -> None: ...
    def get_display_context(
        self, *, sphere_id: int, slug: str
    ) -> EventDisplaySettingsContextDTO: ...
    def update_displayed_fields(
        self, *, sphere_id: int, slug: str, selected_ids: list[int]
    ) -> None: ...
    def get_proposal_settings(
        self, *, sphere_id: int, slug: str
    ) -> EventProposalSettingsDTO: ...
    def update_proposal_settings(
        self, *, sphere_id: int, slug: str, data: ProposalSettingsUpdateData
    ) -> None: ...
