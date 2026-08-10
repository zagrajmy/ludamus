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

from django.db.models import Count

from ludamus.links.db.django.models import Guild, GuildMembership
from ludamus.links.db.django.repositories.storage import save_replacing_files
from ludamus.links.db.django.users import display_avatar_url
from ludamus.pacts.crowd import UserType
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
        email=member.email,
        slug=member.slug,
        avatar_url=display_avatar_url(member),
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
    def find_assignable_users(*, identifier: str) -> list[int]:
        # Mirrors PartyRepository.find_invitable_users: the same handles the
        # party invite accepts, resolved the same way. `username` is never
        # typeable — every account gets a machine-generated one (auth0|...,
        # connected|..., anon_...) — so the Discord column is the one to match.
        # Email is exact-and-unique, so a hit there wins outright; only a
        # Discord handle can be ambiguous, and the caller only needs to tell
        # "one" from "more than one".
        if not (identifier := identifier.strip().lstrip("@")):
            return []
        by_email = (
            User.objects.filter(email__iexact=identifier, user_type=UserType.ACTIVE)
            .order_by("pk")
            .first()
        )
        if by_email is not None:
            return [by_email.pk]
        by_discord = User.objects.filter(
            discord_username__iexact=identifier, user_type=UserType.ACTIVE
        ).order_by("pk")
        return [user.pk for user in by_discord[:2]]

    @staticmethod
    def read_member_guild(*, sphere_id: int, user_pk: int) -> GuildSummaryDTO | None:
        # Both sphere columns, not just the membership's: see marks_for_users.
        membership = (
            GuildMembership.objects.filter(
                sphere_id=sphere_id, guild__sphere_id=sphere_id, member_id=user_pk
            )
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
        # Both `sphere_id` and `guild__sphere_id`, deliberately redundant. The
        # membership's own sphere is what the unique constraint needs, but it is
        # denormalised, so nothing in the schema stops a row pairing sphere A
        # with a guild from sphere B. Only assign_member writes these rows and
        # it guards the pair, but this is a public page: if that guard is ever
        # bypassed, the join is what keeps a foreign sphere's mark off the card
        # rather than repository discipline. One extra join on an indexed FK.
        memberships = GuildMembership.objects.filter(
            sphere_id=sphere_id, guild__sphere_id=sphere_id, member_id__in=user_pks
        ).select_related("guild")
        return {
            membership.member_id: GuildMarkDTO(
                pk=membership.guild.pk,
                name=membership.guild.name,
                logo_url=membership.guild.logo_url,
            )
            for membership in memberships
        }
