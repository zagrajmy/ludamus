from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol


class PlacementRejection(StrEnum):
    NAIVE_DATETIME = "naive_datetime"
    END_NOT_AFTER_START = "end_not_after_start"
    SESSION_NOT_ACCEPTED = "session_not_accepted"


if TYPE_CHECKING:
    from datetime import tzinfo

    from ludamus.pacts.chronology import (
        CapacityHoursDTO,
        ConflictDTO,
        HeatmapDTO,
        MultiselectOptionDTO,
        OfferedTimeViolationDTO,
        SessionPlacement,
        TimetableGridDTO,
        TimetableGridFilter,
        TrackProgressDTO,
    )
    from ludamus.pacts.legacy import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        EventRepositoryProtocol,
        ScheduleChangeLogRepositoryProtocol,
        SessionRepositoryProtocol,
        SpaceDTO,
        SpaceRepositoryProtocol,
        TrackRepositoryProtocol,
    )


class PlacementRejectedError(Exception):
    def __init__(self, reason: PlacementRejection, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class TimetableRepos:
    events: EventRepositoryProtocol
    sessions: SessionRepositoryProtocol
    agenda_items: AgendaItemRepositoryProtocol
    spaces: SpaceRepositoryProtocol
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
    ) -> int: ...
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
        tz: tzinfo,
    ) -> tuple[list[ConflictDTO], list[OfferedTimeViolationDTO]]: ...
    def list_offered_time_violations(
        self, *, event_pk: int, track_pk: int | None, tz: tzinfo
    ) -> list[OfferedTimeViolationDTO]: ...


class TimetableOverviewServiceProtocol(Protocol):
    def get_all_conflicts(self, event_pk: int) -> list[ConflictDTO]: ...
    def build_heatmap(
        self, *, event_pk: int, tz: tzinfo, conflicts: list[ConflictDTO] | None = None
    ) -> HeatmapDTO: ...
    def all_conflicts_grouped(
        self, event_pk: int, conflicts: list[ConflictDTO] | None = None
    ) -> dict[str, list[ConflictDTO]]: ...
    def track_progress(self, event_pk: int) -> list[TrackProgressDTO]: ...
    def capacity_hours(self, *, event_pk: int, tz: tzinfo) -> CapacityHoursDTO: ...
