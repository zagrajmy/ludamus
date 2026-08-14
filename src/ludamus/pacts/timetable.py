from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import tzinfo

    from ludamus.pacts.chronology import (
        CapacityHoursDTO,
        ConflictDTO,
        HeatmapDTO,
        MultiselectOptionDTO,
        PreferredSlotViolationDTO,
        SessionPlacement,
        TimetableGridDTO,
        TimetableGridFilter,
        TrackProgressDTO,
    )
    from ludamus.pacts.legacy import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        ScheduleChangeLogRepositoryProtocol,
        SessionRepositoryProtocol,
        SpaceDTO,
        SpaceRepositoryProtocol,
        TimeSlotRepositoryProtocol,
        TrackRepositoryProtocol,
    )


@dataclass
class TimetableRepos:
    sessions: SessionRepositoryProtocol
    agenda_items: AgendaItemRepositoryProtocol
    spaces: SpaceRepositoryProtocol
    time_slots: TimeSlotRepositoryProtocol
    tracks: TrackRepositoryProtocol
    schedule_change_logs: ScheduleChangeLogRepositoryProtocol


class TimetableServiceProtocol(Protocol):
    def space_filter_options(self, event_pk: int) -> list[MultiselectOptionDTO]: ...
    def build_grid(
        self,
        *,
        event_pk: int,
        tz: tzinfo,
        space_page: int = 1,
        filters: TimetableGridFilter | None = None,
    ) -> TimetableGridDTO: ...
    def assign_session(
        self,
        *,
        session_pk: int,
        placement: SessionPlacement,
        event_pk: int,
        user_pk: int | None = None,
    ) -> None: ...
    def unassign_session(
        self, *, session_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None: ...
    def revert_change(
        self, *, log_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None: ...


class ConflictDetectionServiceProtocol(Protocol):
    def detect_for_assignment(
        self, event_pk: int, session_pk: int
    ) -> list[ConflictDTO]: ...
    def list_all_for_track(
        self, event_pk: int, track_pk: int | None
    ) -> list[ConflictDTO]: ...
    def list_grid_warnings(
        self,
        *,
        event_pk: int,
        track_pk: int | None,
        items: list[AgendaItemDTO],
        spaces: list[SpaceDTO],
    ) -> tuple[list[ConflictDTO], list[PreferredSlotViolationDTO]]: ...
    def list_preferred_slot_violations(
        self, event_pk: int, track_pk: int | None
    ) -> list[PreferredSlotViolationDTO]: ...


class TimetableOverviewServiceProtocol(Protocol):
    def get_all_conflicts(self, event_pk: int) -> list[ConflictDTO]: ...
    def build_heatmap(
        self, *, event_pk: int, tz: tzinfo, conflicts: list[ConflictDTO] | None = None
    ) -> HeatmapDTO: ...
    def all_conflicts_grouped(
        self, event_pk: int, conflicts: list[ConflictDTO] | None = None
    ) -> dict[str, list[ConflictDTO]]: ...
    def track_progress(self, event_pk: int) -> list[TrackProgressDTO]: ...
    def capacity_hours(self, event_pk: int) -> CapacityHoursDTO: ...
