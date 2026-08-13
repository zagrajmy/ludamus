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
        AssignableFacilitatorRef,
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

    def list_facilitator_names(self, *, sphere_id: int) -> list[str]:
        return self._guilds.list_facilitator_names(sphere_id=sphere_id)

    def assign_member(
        self, *, sphere_id: int, guild_pk: int, identifier: str
    ) -> AssignMemberOutcome:
        with self._transaction.atomic():
            matches = self._guilds.find_assignable_users(identifier=identifier)
            if len(matches) > 1:
                return AssignMemberOutcome.AMBIGUOUS_HANDLE
            if len(matches) == 1:
                return self._place_user(
                    sphere_id=sphere_id, guild_pk=guild_pk, user_pk=matches[0]
                )
            found = self._guilds.find_assignable_facilitators(
                sphere_id=sphere_id, name=identifier
            )
            if not found:
                return AssignMemberOutcome.NO_SUCH_USER
            if len(found) > 1:
                return AssignMemberOutcome.AMBIGUOUS_HANDLE
            row = found[0]
            if row.user_id is not None:
                return self._place_user(
                    sphere_id=sphere_id, guild_pk=guild_pk, user_pk=row.user_id
                )
            return self._place_facilitator(
                sphere_id=sphere_id, guild_pk=guild_pk, row=row
            )

    def _place_user(
        self, *, sphere_id: int, guild_pk: int, user_pk: int
    ) -> AssignMemberOutcome:
        # Read the presenter's current guild before writing, so the view can
        # say "moved from X" instead of silently reassigning them.
        current = self._guilds.read_member_guild(sphere_id=sphere_id, user_pk=user_pk)
        if current is not None and current.pk == guild_pk:
            return AssignMemberOutcome.ALREADY_MEMBER
        if not self._guilds.assign_member(
            sphere_id=sphere_id, guild_pk=guild_pk, user_pk=user_pk
        ):
            return AssignMemberOutcome.NO_SUCH_USER
        if current is not None:
            return AssignMemberOutcome.MOVED
        return AssignMemberOutcome.ASSIGNED

    def _place_facilitator(
        self, *, sphere_id: int, guild_pk: int, row: AssignableFacilitatorRef
    ) -> AssignMemberOutcome:
        if row.guild_id == guild_pk:
            return AssignMemberOutcome.ALREADY_MEMBER
        if not self._guilds.set_facilitator_guild(
            sphere_id=sphere_id, facilitator_pk=row.pk, guild_pk=guild_pk
        ):
            return AssignMemberOutcome.NO_SUCH_USER
        if row.guild_id is not None:
            return AssignMemberOutcome.MOVED
        return AssignMemberOutcome.ASSIGNED

    def remove_member(
        self, *, sphere_id: int, guild_pk: int, membership_pk: int
    ) -> bool:
        with self._transaction.atomic():
            return self._guilds.remove_member(
                sphere_id=sphere_id, guild_pk=guild_pk, membership_pk=membership_pk
            )

    def clear_facilitator(
        self, *, sphere_id: int, guild_pk: int, facilitator_pk: int
    ) -> bool:
        with self._transaction.atomic():
            return self._guilds.clear_facilitator(
                sphere_id=sphere_id, guild_pk=guild_pk, facilitator_pk=facilitator_pk
            )

    def marks_for_facilitators(
        self, *, sphere_id: int, facilitator_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        return self._guilds.marks_for_facilitators(
            sphere_id=sphere_id, facilitator_pks=facilitator_pks
        )

    def mark_for_facilitator(
        self, *, sphere_id: int, facilitator_pk: int
    ) -> GuildMarkDTO | None:
        return self._guilds.marks_for_facilitators(
            sphere_id=sphere_id, facilitator_pks=[facilitator_pk]
        ).get(facilitator_pk)

    def marks_for_sessions(
        self, *, sphere_id: int, session_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        return self._guilds.marks_for_sessions(
            sphere_id=sphere_id, session_pks=session_pks
        )

    def mark_for_session(
        self, *, sphere_id: int, session_pk: int
    ) -> GuildMarkDTO | None:
        # A single card (the modal) shouldn't have to unpack a batch dict, and
        # a presenter-less session shouldn't have to guard the call.
        return self._guilds.marks_for_sessions(
            sphere_id=sphere_id, session_pks=[session_pk]
        ).get(session_pk)
