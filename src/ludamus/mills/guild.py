"""Guild noun business logic.

Sphere-manager-facing guild CRUD and roster assignment. Django-free; receives
the repo protocol and a transaction. Every method takes the sphere id from the
caller's request context, and the repository re-checks it on the same query as
each write, so a foreign guild pk fails as "not found" rather than leaking that
it exists elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.slugs import unique_slug
from ludamus.pacts.guild import (
    AssignMemberOutcome,
    DeleteGuildOutcome,
    GuildServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.guild import (
        GuildDTO,
        GuildMarkDTO,
        GuildRepositoryProtocol,
        GuildSummaryDTO,
        GuildWriteData,
    )
    from ludamus.pacts.services import TransactionProtocol


class GuildService(GuildServiceProtocol):
    def __init__(
        self, *, transaction: TransactionProtocol, guilds: GuildRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._guilds = guilds

    def list_for_sphere(self, *, sphere_id: int) -> list[GuildSummaryDTO]:
        return self._guilds.list_for_sphere(sphere_id=sphere_id)

    def read(self, *, sphere_id: int, guild_pk: int) -> GuildDTO | None:
        return self._guilds.read(sphere_id=sphere_id, guild_pk=guild_pk)

    def create(self, *, sphere_id: int, base_slug: str, data: GuildWriteData) -> int:
        with self._transaction.atomic():
            # The gate slugifies the name (mills cannot import Django's
            # slugify); uniquifying it against the sphere happens here. The
            # check and the insert are not atomic against each other under READ
            # COMMITTED, so what actually keeps slugs unique is the constraint
            # on (sphere, slug) — two managers creating the same guild name in
            # the same second means one of them sees an error and retries by
            # hand. Rare enough to leave; not rare enough to lie about.
            slug = unique_slug(
                base=base_slug,
                default="guild",
                exists=lambda candidate: self._guilds.slug_exists(
                    sphere_id=sphere_id, slug=candidate
                ),
            )
            return self._guilds.create(sphere_id=sphere_id, data={**data, "slug": slug})

    def update(self, *, sphere_id: int, guild_pk: int, data: GuildWriteData) -> bool:
        # Deliberately leaves `slug` alone: renaming a guild must not break a
        # link a manager already shared.
        with self._transaction.atomic():
            return self._guilds.update(
                sphere_id=sphere_id, guild_pk=guild_pk, data=data
            )

    def delete(self, *, sphere_id: int, guild_pk: int) -> DeleteGuildOutcome:
        with self._transaction.atomic():
            if not self._guilds.delete(sphere_id=sphere_id, guild_pk=guild_pk):
                return DeleteGuildOutcome.NOT_FOUND
            return DeleteGuildOutcome.DELETED

    def assign_member(
        self, *, sphere_id: int, guild_pk: int, identifier: str
    ) -> AssignMemberOutcome:
        with self._transaction.atomic():
            matches = self._guilds.find_assignable_users(identifier=identifier)
            if not matches:
                return AssignMemberOutcome.NO_SUCH_USER
            if len(matches) > 1:
                return AssignMemberOutcome.AMBIGUOUS_HANDLE
            user_pk = matches[0]
            # Read the presenter's current guild before writing, so the view can
            # say "moved from X" instead of silently reassigning them.
            current = self._guilds.read_member_guild(
                sphere_id=sphere_id, user_pk=user_pk
            )
            if current is not None and current.pk == guild_pk:
                return AssignMemberOutcome.ALREADY_MEMBER
            if not self._guilds.assign_member(
                sphere_id=sphere_id, guild_pk=guild_pk, user_pk=user_pk
            ):
                return AssignMemberOutcome.NO_SUCH_USER
            if current is not None:
                return AssignMemberOutcome.MOVED
            return AssignMemberOutcome.ASSIGNED

    def remove_member(
        self, *, sphere_id: int, guild_pk: int, membership_pk: int
    ) -> bool:
        with self._transaction.atomic():
            return self._guilds.remove_member(
                sphere_id=sphere_id, guild_pk=guild_pk, membership_pk=membership_pk
            )

    def marks_for_users(
        self, *, sphere_id: int, user_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        return self._guilds.marks_for_users(sphere_id=sphere_id, user_pks=user_pks)

    def mark_for_user(
        self, *, sphere_id: int, user_pk: int | None
    ) -> GuildMarkDTO | None:
        # A single card (the modal) shouldn't have to unpack a batch dict, and
        # a presenter-less session shouldn't have to guard the call.
        marks = self._guilds.marks_for_users(
            sphere_id=sphere_id, user_pks=[user_pk] if user_pk else []
        )
        return marks.get(user_pk) if user_pk else None
