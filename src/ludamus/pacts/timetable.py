from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from ludamus.pacts.legacy import TimeSlotDTO


class PlacementRejection(StrEnum):
    NAIVE_DATETIME = "naive_datetime"
    END_NOT_AFTER_START = "end_not_after_start"
    OUTSIDE_TIME_SLOTS = "outside_time_slots"
    SESSION_NOT_ACCEPTED = "session_not_accepted"
    SESSION_NOT_PENDING = "session_not_pending"
    SPACE_TAKEN = "space_taken"


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
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        ScheduleChangeLogRepositoryProtocol,
        SessionRepositoryProtocol,
        SpaceDTO,
        SpaceRepositoryProtocol,
        SphereRepositoryProtocol,
        TimeSlotRepositoryProtocol,
        TrackRepositoryProtocol,
    )


class PlacementRejectedError(Exception):
    def __init__(self, reason: PlacementRejection, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class ClaimPermissionRepos:
    """What deciding who may release a walk-up claim needs, and nothing else.

    Grouped rather than spread across `TimetableRepos`: a claim may be
    withdrawn by its own author as well as by an organizer, so the permission
    is a rule the service applies, not the panel access a caller proved.
    """

    active_users: UserRepositoryProtocol
    spheres: SphereRepositoryProtocol


@dataclass
class TimetableRepos:
    sessions: SessionRepositoryProtocol
    agenda_items: AgendaItemRepositoryProtocol
    spaces: SpaceRepositoryProtocol
    time_slots: TimeSlotRepositoryProtocol
    tracks: TrackRepositoryProtocol
    schedule_change_logs: ScheduleChangeLogRepositoryProtocol
    claim_permissions: ClaimPermissionRepos


class FreeSpotSpaceDTO(BaseModel):
    """One bookable room and the time slots nothing occupies it for."""

    pk: int
    name: str
    # The immediate-parent name this room groups under; empty at root level.
    group: str
    slots: list[TimeSlotDTO]


class TimetableServiceProtocol(Protocol):
    def space_filter_options(self, event_pk: int) -> list[MultiselectOptionDTO]: ...
    def list_free_spots(self, event_pk: int) -> list[FreeSpotSpaceDTO]: ...
    def claim_spot(
        self,
        *,
        session_pk: int,
        placement: SessionPlacement,
        event_pk: int,
        user_pk: int,
    ) -> None: ...
    def release_claim(
        self, *, session_pk: int, event_pk: int, user_pk: int, user_slug: str
    ) -> None: ...
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
