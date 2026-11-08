"""Facilitators: the people a session names, and their change log."""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.sessions import ContentFieldChange

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.event import FacilitatorListItemDTO
    from ludamus.pacts.submissions import (
        FacilitatorListFilters,
        FacilitatorSessionCountsDTO,
    )
    from ludamus.pacts.timetable import (
        ConfirmationCountsRow,
        ConfirmationFacilitatorRow,
    )


class FacilitatorDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accreditation_type: str
    deleted_at: datetime | None = None
    display_name: str
    event_id: int
    guild_id: int | None = None
    ident: str = ""
    internal_comment: str = ""
    is_collective: bool = False
    organizer_id: int | None = None
    # Annotated by the single-facilitator reads, so a page showing the
    # organizer needs no second lookup. `create` and `update` return the row
    # they just wrote, without it.
    organizer_name: str | None = None
    pk: int
    slug: str
    user_id: int | None


class FacilitatorData(TypedDict, total=False):
    accreditation_type: str
    display_name: str
    event_id: int
    ident: str
    is_collective: bool
    organizer_id: int | None
    slug: str
    user_id: int | None


class FacilitatorUpdateData(TypedDict, total=False):
    accreditation_type: str
    display_name: str
    guild_id: int | None
    internal_comment: str
    is_collective: bool
    organizer_id: int | None
    user_id: int | None


class FacilitatorRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: FacilitatorData) -> FacilitatorDTO: ...
    @staticmethod
    def read(pk: int) -> FacilitatorDTO: ...
    @staticmethod
    def read_by_event_and_slug(event_id: int, slug: str) -> FacilitatorDTO: ...
    @staticmethod
    def find_by_event_and_display_name(
        event_id: int, display_name: str
    ) -> FacilitatorDTO | None: ...
    @staticmethod
    def read_including_deleted(event_id: int, slug: str) -> FacilitatorDTO: ...
    @staticmethod
    def read_by_user_and_event(user_id: int, event_id: int) -> FacilitatorDTO: ...
    @staticmethod
    def find_by_ident(event_id: int, ident: str) -> FacilitatorDTO | None: ...
    @staticmethod
    def set_ident(pk: int, ident: str) -> None: ...
    @staticmethod
    def update(pk: int, data: FacilitatorUpdateData) -> FacilitatorDTO: ...
    @staticmethod
    def set_accreditation(
        *, event_id: int, pks: list[int], accreditation_type: str
    ) -> None: ...
    @staticmethod
    def list_by_event(
        event_id: int, filters: FacilitatorListFilters | None = None
    ) -> list[FacilitatorListItemDTO]: ...
    @staticmethod
    def list_deleted_by_event(event_id: int) -> list[FacilitatorListItemDTO]: ...
    @staticmethod
    def list_by_slugs(
        event_id: int, facilitator_slugs: list[str]
    ) -> list[FacilitatorListItemDTO]: ...
    @staticmethod
    def claim(pk: int, organizer_id: int) -> bool: ...
    @staticmethod
    def release(pk: int, *, organizer_id: int | None) -> bool: ...
    @staticmethod
    def count_confirmations_by_organizer(
        event_pk: int,
    ) -> list[ConfirmationCountsRow]: ...
    @staticmethod
    def list_with_scheduled_session_in_track(
        event_pk: int, track_pk: int
    ) -> list[ConfirmationFacilitatorRow]: ...
    @staticmethod
    def lock(pks: Iterable[int]) -> None: ...
    @staticmethod
    def lock_by_event_and_slugs(
        event_id: int, slugs: list[str]
    ) -> list[FacilitatorDTO]: ...
    @staticmethod
    def count_sessions(pk: int) -> FacilitatorSessionCountsDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def soft_delete(pk: int) -> None: ...
    @staticmethod
    def restore(pk: int) -> None: ...
    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool: ...


class FacilitatorChangeLogData(TypedDict):
    event_id: int
    facilitator_id: int
    user_id: int | None
    changes: list[ContentFieldChange]


class FacilitatorChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    facilitator_id: int
    facilitator_name: str
    user_id: int | None
    user_name: str
    changes: list[ContentFieldChange]
    creation_time: datetime

    @property
    def item_name(self) -> str:
        # See ContentChangeLogDTO.item_name.
        return self.facilitator_name


class FacilitatorChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: FacilitatorChangeLogData) -> None: ...

    @staticmethod
    def create_many(data: list[FacilitatorChangeLogData]) -> None: ...

    @staticmethod
    def list_by_event(event_pk: int) -> list[FacilitatorChangeLogDTO]: ...
