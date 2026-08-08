"""Guild noun contracts.

A guild is an association, club, studio or podcast that a sphere's programme
creators belong to — Topory, Tol Calen, Copernicus Corporation. Sphere managers
own the whole lifecycle: they create the guild, upload its mark, and assign
presenters to it. Presenters never self-assign, so there is no
participant-facing port here.

A presenter belongs to at most one guild per sphere: the mark rendered beside
their name on a programme card has to be unambiguous, so `assign_member` moves
a presenter between guilds rather than accumulating memberships.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


class AssignMemberOutcome(StrEnum):
    ASSIGNED = "assigned"
    # Reassigned from another guild in the same sphere; the view tells the
    # manager which one, so a silent move can't look like a plain add.
    MOVED = "moved"
    ALREADY_MEMBER = "already_member"
    NO_SUCH_USER = "no_such_user"
    AMBIGUOUS_HANDLE = "ambiguous_handle"


class DeleteGuildOutcome(StrEnum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"


class GuildWriteData(TypedDict, total=False):
    name: str
    slug: str
    # None keeps the stored mark, "" removes it, a file replaces it — the
    # tri-state resolve_uploaded_file_field returns.
    logo: UploadedFileProtocol | str


class GuildMemberDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_pk: int
    user_pk: int
    name: str
    full_name: str
    email: str
    slug: str
    # Machine-generated (auth0|…, connected|…, anon_…) and never shown, but
    # components/avatar.html resolves it as the last fallback in its name
    # chain, and Django resolves every branch of a `|default:` chain.
    username: str
    avatar_url: str = ""


class GuildSummaryDTO(BaseModel):
    """List-page row: no roster, so the page costs one query plus a count."""

    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    slug: str
    logo_url: str = ""
    member_count: int = 0


class GuildDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    slug: str
    logo_url: str = ""
    members: list[GuildMemberDTO]


class GuildMarkDTO(BaseModel):
    """The card-sized slice: enough to draw the notch and label it.

    Deliberately without the roster — a programme card is public, and who
    belongs to a guild is panel-only information.
    """

    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    logo_url: str = ""


class GuildRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_sphere(*, sphere_id: int) -> list[GuildSummaryDTO]: ...
    @staticmethod
    def read(*, sphere_id: int, guild_pk: int) -> GuildDTO | None: ...
    @staticmethod
    def create(*, sphere_id: int, data: GuildWriteData) -> int: ...
    @staticmethod
    def slug_exists(*, sphere_id: int, slug: str) -> bool: ...
    @staticmethod
    def update(*, sphere_id: int, guild_pk: int, data: GuildWriteData) -> bool: ...
    @staticmethod
    def delete(*, sphere_id: int, guild_pk: int) -> bool: ...
    @staticmethod
    def find_assignable_users(*, identifier: str) -> list[int]: ...
    @staticmethod
    def read_member_guild(
        *, sphere_id: int, user_pk: int
    ) -> GuildSummaryDTO | None: ...
    @staticmethod
    def assign_member(*, sphere_id: int, guild_pk: int, user_pk: int) -> bool: ...
    @staticmethod
    def remove_member(*, sphere_id: int, guild_pk: int, membership_pk: int) -> bool: ...
    @staticmethod
    def marks_for_users(
        *, sphere_id: int, user_pks: list[int]
    ) -> dict[int, GuildMarkDTO]: ...


class GuildServiceProtocol(Protocol):
    def list_for_sphere(self, *, sphere_id: int) -> list[GuildSummaryDTO]: ...
    def read(self, *, sphere_id: int, guild_pk: int) -> GuildDTO | None: ...
    def create(
        self, *, sphere_id: int, base_slug: str, data: GuildWriteData
    ) -> int: ...
    def update(
        self, *, sphere_id: int, guild_pk: int, data: GuildWriteData
    ) -> bool: ...
    def delete(self, *, sphere_id: int, guild_pk: int) -> DeleteGuildOutcome: ...
    def assign_member(
        self, *, sphere_id: int, guild_pk: int, identifier: str
    ) -> AssignMemberOutcome: ...
    def remove_member(
        self, *, sphere_id: int, guild_pk: int, membership_pk: int
    ) -> bool: ...
    def marks_for_users(
        self, *, sphere_id: int, user_pks: list[int]
    ) -> dict[int, GuildMarkDTO]: ...
    def mark_for_user(
        self, *, sphere_id: int, user_pk: int | None
    ) -> GuildMarkDTO | None: ...
