"""Repository for the guild noun.

Implements `GuildRepositoryProtocol`. Every method is sphere-scoped: the
sphere id comes from the request context, never from the URL, so a manager of
one sphere cannot read or touch another sphere's guilds by guessing a pk.
Ownership guards live in the queries as filter clauses, mirroring the party
repository's style — a non-matching sphere updates zero rows and the boolean
return carries the verdict.

Which store a facilitator uses, and which person a session card shows, is
decided here rather than in the mill: the public programme pages need one
query for a whole grid, and the rule is a join-and-pick over rows the mill
would otherwise re-fetch as DTOs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from django.db.models import Count, Q

from ludamus.links.db.django.models import Facilitator, Guild, GuildMembership, Session
from ludamus.links.db.django.repositories.storage import (
    save_replacing_files,
    with_original_names,
)
from ludamus.links.db.django.users import display_avatar_url
from ludamus.pacts.crowd import UserType
from ludamus.pacts.guild import (
    AssignableFacilitatorRef,
    GuildDTO,
    GuildFacilitatorMemberDTO,
    GuildMarkDTO,
    GuildMemberDTO,
    GuildMembershipMemberDTO,
    GuildRepositoryProtocol,
    GuildSummaryDTO,
    GuildWriteData,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ludamus.links.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


def _member_dto(membership: GuildMembership) -> GuildMembershipMemberDTO:
    member = membership.member
    return GuildMembershipMemberDTO(
        membership_pk=membership.pk,
        name=member.name,
        full_name=member.full_name,
        email=member.email or None,
        avatar_url=display_avatar_url(member),
    )


def _facilitator_member_dto(facilitator: Facilitator) -> GuildFacilitatorMemberDTO:
    return GuildFacilitatorMemberDTO(
        facilitator_pk=facilitator.pk,
        name=facilitator.display_name,
        event_name=facilitator.event.name,
    )


def _roster_sort_key(
    member: GuildMembershipMemberDTO | GuildFacilitatorMemberDTO,
) -> tuple[str, str, int]:
    match member:
        case GuildFacilitatorMemberDTO(
            name=name, event_name=event_name, facilitator_pk=pk
        ):
            return (name, event_name, pk)
        case GuildMembershipMemberDTO(name=name, membership_pk=pk):
            return (name, "", pk)


def _mark(guild: Guild) -> GuildMarkDTO:
    return GuildMarkDTO(pk=guild.pk, name=guild.name, logo_url=guild.logo_url)


_LOGO_STORAGE = Guild.logo.field.storage


def _mark_from_columns(*, pk: int, name: str, logo: str) -> GuildMarkDTO:
    # The same mark _mark builds from an instance, off a values_list row: the
    # schedule asks for a thousand sessions' co-facilitators at once, and a
    # model per row with its guild joined in cost more than the page's SQL.
    return GuildMarkDTO(
        pk=pk, name=name, logo_url=_LOGO_STORAGE.url(logo) if logo else ""
    )


class _CoFacilitator(NamedTuple):
    # A presenter-less session's co-facilitator, as much of one as a mark
    # needs: an account to look the membership up by, or the guild the
    # accountless row names directly.
    user_id: int | None
    guild: GuildMarkDTO | None


def _accountless_on_guild(*, guild_id: int, sphere_id: int) -> QuerySet[Facilitator]:
    return Facilitator.objects.filter(
        guild_id=guild_id, event__sphere_id=sphere_id, user_id__isnull=True
    ).select_related("event")


def _facilitators_in_sphere(*, sphere_id: int) -> QuerySet[Facilitator]:
    # Same defence as marks_for_users: a guild FK can point at another sphere's
    # row, so the join is what keeps a foreign mark off the card.
    return Facilitator.objects.filter(event__sphere_id=sphere_id).filter(
        Q(guild__isnull=True) | Q(guild__sphere_id=sphere_id)
    )


def _mark_for_facilitator(
    facilitator: Facilitator, *, by_user: dict[int, GuildMarkDTO]
) -> GuildMarkDTO | None:
    if facilitator.user_id:
        return by_user.get(facilitator.user_id)
    if facilitator.guild is not None:
        return _mark(facilitator.guild)
    return None


def _mark_for_session(
    *,
    session_pk: int,
    presenter_id: int | None,
    by_session: dict[int, list[_CoFacilitator]],
    by_user: dict[int, GuildMarkDTO],
) -> GuildMarkDTO | None:
    if presenter_id:
        return by_user.get(presenter_id)
    # Presenter-less cards show the first co-facilitator that has a mark,
    # ordered by display name then pk so the badge is stable across loads.
    for facilitator in by_session.get(session_pk, []):
        found = (
            by_user.get(facilitator.user_id)
            if facilitator.user_id
            else facilitator.guild
        )
        if found:
            return found
    return None


def marks_for_users(*, sphere_id: int, user_pks: list[int]) -> dict[int, GuildMarkDTO]:
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
    return {membership.member_id: _mark(membership.guild) for membership in memberships}


class GuildRepository(GuildRepositoryProtocol):
    @staticmethod
    def list_for_sphere(*, sphere_id: int) -> list[GuildSummaryDTO]:
        guilds = (
            Guild.objects
            .filter(sphere_id=sphere_id)
            .annotate(
                # Two reverse relations in one annotate would otherwise
                # multiply rows; distinct keeps each count as a count of
                # rows, not of the join product.
                member_count_annotated=Count("memberships", distinct=True)
                + Count(
                    "facilitators",
                    filter=Q(
                        facilitators__user_id__isnull=True,
                        facilitators__event__sphere_id=sphere_id,
                    ),
                    distinct=True,
                )
            )
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
            Guild.objects
            .filter(pk=guild_pk, sphere_id=sphere_id)
            .prefetch_related("memberships__member")
            .first()
        )
        if guild is None:
            return None
        members: list[GuildMemberDTO] = [
            _member_dto(row) for row in guild.memberships.all()
        ]
        members.extend(
            _facilitator_member_dto(row)
            for row in _accountless_on_guild(guild_id=guild.pk, sphere_id=sphere_id)
        )
        members.sort(key=_roster_sort_key)
        return GuildDTO(
            pk=guild.pk,
            name=guild.name,
            slug=guild.slug,
            logo_url=guild.logo_url,
            logo_original_name=guild.logo_original_name,
            members=members,
        )

    @staticmethod
    def create(*, sphere_id: int, data: GuildWriteData) -> int:
        return Guild.objects.create(
            sphere_id=sphere_id, **with_original_names(Guild, data)
        ).pk

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
    def list_facilitator_names(*, sphere_id: int) -> list[str]:
        return list(
            Facilitator.objects
            .filter(event__sphere_id=sphere_id)
            .exclude(display_name="")
            .order_by("display_name")
            .values_list("display_name", flat=True)
            .distinct()
        )

    @staticmethod
    def find_assignable_facilitators(
        *, sphere_id: int, name: str
    ) -> list[AssignableFacilitatorRef]:
        if not (name := name.strip()):
            return []
        rows = (
            Facilitator.objects
            .filter(event__sphere_id=sphere_id, display_name__iexact=name)
            .order_by("pk")
            .values_list("pk", "user_id", "guild_id")
        )
        return [
            AssignableFacilitatorRef(pk=pk, user_id=user_id, guild_id=guild_id)
            for pk, user_id, guild_id in rows
        ]

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
            User.objects
            .filter(email__iexact=identifier, user_type=UserType.ACTIVE)
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
            GuildMembership.objects
            .filter(sphere_id=sphere_id, guild__sphere_id=sphere_id, member_id=user_pk)
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
    def set_facilitator_guild(
        *, sphere_id: int, facilitator_pk: int, guild_pk: int
    ) -> bool:
        if not Guild.objects.filter(pk=guild_pk, sphere_id=sphere_id).exists():
            return False
        updated = Facilitator.objects.filter(
            pk=facilitator_pk, user__isnull=True, event__sphere_id=sphere_id
        ).update(guild_id=guild_pk)
        return bool(updated)

    @staticmethod
    def clear_facilitator(
        *, sphere_id: int, guild_pk: int, facilitator_pk: int
    ) -> bool:
        updated = Facilitator.objects.filter(
            pk=facilitator_pk, guild_id=guild_pk, event__sphere_id=sphere_id
        ).update(guild_id=None)
        return bool(updated)

    @staticmethod
    def marks_for_facilitators(
        *, sphere_id: int, facilitator_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        if not facilitator_pks:
            return {}
        rows = list(
            _facilitators_in_sphere(sphere_id=sphere_id)
            .filter(pk__in=facilitator_pks)
            .select_related("guild")
        )
        by_user = marks_for_users(
            sphere_id=sphere_id, user_pks=[row.user_id for row in rows if row.user_id]
        )
        marks: dict[int, GuildMarkDTO] = {}
        for row in rows:
            if found := _mark_for_facilitator(row, by_user=by_user):
                marks[row.pk] = found
        return marks

    @staticmethod
    def marks_for_sessions(
        *, sphere_id: int, session_pks: list[int]
    ) -> dict[int, GuildMarkDTO]:
        if not session_pks:
            return {}
        # Two columns, not instances: a page of a thousand rows asks this once.
        sessions = list(
            Session.objects.filter(
                pk__in=session_pks, event__sphere_id=sphere_id
            ).values_list("pk", "presenter_id")
        )
        if not sessions:
            return {}
        presenter_ids = [presenter_id for _, presenter_id in sessions if presenter_id]
        presenter_less_pks = [pk for pk, presenter_id in sessions if not presenter_id]
        by_session: dict[int, list[_CoFacilitator]] = {}
        facilitator_user_ids: list[int] = []
        if presenter_less_pks:
            # sessions__pk in the filter and in the columns rides one join:
            # the filter opens it first, and the values_list reuses it.
            rows = (
                _facilitators_in_sphere(sphere_id=sphere_id)
                .filter(sessions__pk__in=presenter_less_pks)
                .order_by("display_name", "pk")
                .values_list(
                    "sessions__pk", "user_id", "guild_id", "guild__name", "guild__logo"
                )
            )
            for session_pk, user_id, guild_id, guild_name, guild_logo in rows:
                by_session.setdefault(session_pk, []).append(
                    _CoFacilitator(
                        user_id=user_id,
                        guild=(
                            _mark_from_columns(
                                pk=guild_id, name=guild_name, logo=guild_logo
                            )
                            if guild_id
                            else None
                        ),
                    )
                )
                if user_id:
                    facilitator_user_ids.append(user_id)
        by_user = marks_for_users(
            sphere_id=sphere_id, user_pks=presenter_ids + facilitator_user_ids
        )
        marks: dict[int, GuildMarkDTO] = {}
        for pk, presenter_id in sessions:
            if found := _mark_for_session(
                session_pk=pk,
                presenter_id=presenter_id,
                by_session=by_session,
                by_user=by_user,
            ):
                marks[pk] = found
        return marks
