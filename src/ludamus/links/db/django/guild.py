"""Repository for the guild noun.

Implements `GuildRepositoryProtocol`. Every method is sphere-scoped: the
sphere id comes from the request context, never from the URL, so a manager of
one sphere cannot read or touch another sphere's guilds by guessing a pk.
Ownership guards live in the queries as filter clauses, mirroring the party
repository's style — a non-matching sphere updates zero rows and the boolean
return carries the verdict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count, Q

from ludamus.links.db.django.models import Guild, GuildMembership
from ludamus.links.db.django.repositories.storage import save_replacing_files
from ludamus.pacts.guild import (
    GuildDTO,
    GuildMarkDTO,
    GuildMemberDTO,
    GuildRepositoryProtocol,
    GuildSummaryDTO,
    GuildWriteData,
)

if TYPE_CHECKING:
    from ludamus.links.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


def _member_dto(membership: GuildMembership) -> GuildMemberDTO:
    member = membership.member
    return GuildMemberDTO(
        membership_pk=membership.pk,
        user_pk=member.pk,
        name=member.name,
        full_name=member.full_name,
        username=member.username,
        slug=member.slug,
        avatar_url=member.avatar_url or "",
    )


def _user_dto(user: User) -> GuildMemberDTO:
    # A candidate is not a member yet, so there is no membership row to point
    # at; 0 marks "unsaved" and never reaches a template.
    return GuildMemberDTO(
        membership_pk=0,
        user_pk=user.pk,
        name=user.name,
        full_name=user.full_name,
        username=user.username,
        slug=user.slug,
        avatar_url=user.avatar_url or "",
    )


class GuildRepository(GuildRepositoryProtocol):
    @staticmethod
    def list_for_sphere(*, sphere_id: int) -> list[GuildSummaryDTO]:
        guilds = (
            Guild.objects.filter(sphere_id=sphere_id)
            .annotate(member_count_annotated=Count("memberships"))
            .order_by("name")
        )
        return [
            GuildSummaryDTO(
                pk=guild.pk,
                name=guild.name,
                slug=guild.slug,
                logo_url=guild.logo_url,
                member_count=guild.member_count_annotated,
            )
            for guild in guilds
        ]

    @staticmethod
    def read(*, sphere_id: int, guild_pk: int) -> GuildDTO | None:
        guild = (
            Guild.objects.filter(pk=guild_pk, sphere_id=sphere_id)
            .prefetch_related("memberships__member")
            .first()
        )
        if guild is None:
            return None
        memberships = sorted(guild.memberships.all(), key=lambda m: m.member.name)
        return GuildDTO(
            pk=guild.pk,
            name=guild.name,
            slug=guild.slug,
            logo_url=guild.logo_url,
            members=[_member_dto(membership) for membership in memberships],
        )

    @staticmethod
    def create(*, sphere_id: int, data: GuildWriteData) -> int:
        return Guild.objects.create(sphere_id=sphere_id, **data).pk

    @staticmethod
    def slug_exists(*, sphere_id: int, slug: str) -> bool:
        return Guild.objects.filter(sphere_id=sphere_id, slug=slug).exists()

    @staticmethod
    def update(*, sphere_id: int, guild_pk: int, data: GuildWriteData) -> bool:
        guild = Guild.objects.filter(pk=guild_pk, sphere_id=sphere_id).first()
        if guild is None:
            return False
        # save_replacing_files, not .update(): a replaced logo would otherwise
        # strand its previous blob, since unique_upload_to never reuses a name.
        save_replacing_files(guild, dict(data))
        return True

    @staticmethod
    def delete(*, sphere_id: int, guild_pk: int) -> bool:
        deleted, __ = Guild.objects.filter(pk=guild_pk, sphere_id=sphere_id).delete()
        return bool(deleted)

    @staticmethod
    def find_assignable_users(*, identifier: str) -> list[GuildMemberDTO]:
        # Same handles the party invite accepts: the account email or the
        # Discord username they signed up with. Capped at three because the
        # caller only needs to tell "one" from "more than one".
        candidates = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        ).order_by("pk")[:3]
        return [_user_dto(user) for user in candidates]

    @staticmethod
    def read_member_guild(*, sphere_id: int, user_pk: int) -> GuildSummaryDTO | None:
        membership = (
            GuildMembership.objects.filter(sphere_id=sphere_id, member_id=user_pk)
            .select_related("guild")
            .first()
        )
        if membership is None:
            return None
        guild = membership.guild
        return GuildSummaryDTO(
            pk=guild.pk, name=guild.name, slug=guild.slug, logo_url=guild.logo_url
        )

    @staticmethod
    def assign_member(*, sphere_id: int, guild_pk: int, user_pk: int) -> bool:
        # The guild must belong to this sphere; checking it here rather than in
        # the service keeps the guard on the same query as the write.
        if not Guild.objects.filter(pk=guild_pk, sphere_id=sphere_id).exists():
            return False
        # One guild per presenter per sphere: update_or_create moves an existing
        # membership instead of adding a second one, which the unique constraint
        # on (sphere, member) would reject anyway.
        GuildMembership.objects.update_or_create(
            sphere_id=sphere_id, member_id=user_pk, defaults={"guild_id": guild_pk}
        )
        return True

    @staticmethod
    def remove_member(*, sphere_id: int, guild_pk: int, membership_pk: int) -> bool:
        deleted, __ = GuildMembership.objects.filter(
            pk=membership_pk, guild_id=guild_pk, sphere_id=sphere_id
        ).delete()
        return bool(deleted)

    @staticmethod
    def marks_for_users(
        *, sphere_id: int, user_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        # One query for a whole page of cards; the caller indexes by presenter
        # pk. Empty in, empty out — no query for a page of guild-less sessions.
        if not user_pks:
            return {}
        memberships = GuildMembership.objects.filter(
            sphere_id=sphere_id, member_id__in=user_pks
        ).select_related("guild")
        return {
            membership.member_id: GuildMarkDTO(
                pk=membership.guild.pk,
                name=membership.guild.name,
                logo_url=membership.guild.logo_url,
            )
            for membership in memberships
        }
