from datetime import UTC, datetime, timedelta

from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Subquery

from ludamus.links.db.django.models import (
    Encounter,
    EncounterInvitee,
    EncounterRSVP,
    User,
)
from ludamus.links.db.django.repositories.storage import (
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts import (
    EncounterData,
    EncounterDTO,
    EncounterRepositoryProtocol,
    EncounterRSVPDTO,
    EncounterRSVPRepositoryProtocol,
    NotFoundError,
)
from ludamus.pacts.crowd import UserType
from ludamus.pacts.encounter import (
    EncounterInviteeDTO,
    EncounterInviteeRepositoryProtocol,
    InviteeStatus,
)


class EncounterRepository(EncounterRepositoryProtocol):
    @staticmethod
    def create(data: EncounterData) -> EncounterDTO:
        encounter = Encounter.objects.create(**with_original_names(Encounter, data))
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def exists_for_sphere(sphere_id: int) -> bool:
        return Encounter.objects.filter(sphere_id=sphere_id).exists()

    # Both reads take the sphere: share codes and pks are globally unique, so
    # without it a route served under one sphere could reach another's
    # encounter and sidestep that sphere's encounters page being disabled.
    @staticmethod
    def read(pk: int, sphere_id: int) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(pk=pk, sphere_id=sphere_id)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def read_by_share_code(share_code: str, sphere_id: int) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(
                share_code=share_code, sphere_id=sphere_id
            )
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    # NOTE: sphere-free on purpose, for calendar replies arriving by mail; the
    # caller must first prove the reply answers an invite we sent.
    @staticmethod
    def read_by_share_code_in_any_sphere(share_code: str) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(share_code=share_code)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    # What a given visitor may see of a sphere's encounters: the listed ones,
    # plus the ones they organise or hold an RSVP to. An anonymous visitor has
    # neither, so they see the listed ones alone.
    @staticmethod
    def _visible(sphere_id: int, user_id: int | None) -> QuerySet[Encounter]:
        visible = Q(is_public=True)
        if user_id is not None:
            visible |= Q(creator_id=user_id) | Q(rsvps__user_id=user_id)
        return Encounter.objects.filter(visible, sphere_id=sphere_id).distinct()

    # "Past" means ended, matching how the events feed splits its own items —
    # the two sit in one grid. An encounter with no end time ends when it
    # starts, since nothing says how long it runs.
    @staticmethod
    def _ended() -> Q:
        now = datetime.now(tz=UTC)
        return Q(end_time__lt=now) | Q(end_time__isnull=True, start_time__lt=now)

    @staticmethod
    def list_visible_upcoming(
        sphere_id: int, user_id: int | None, *, limit: int | None = None
    ) -> list[EncounterDTO]:
        encounters = (
            EncounterRepository._visible(sphere_id, user_id)
            .exclude(EncounterRepository._ended())
            .order_by("start_time")[:limit]
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_visible_past(
        sphere_id: int, user_id: int | None, *, limit: int
    ) -> list[EncounterDTO]:
        encounters = (
            EncounterRepository._visible(sphere_id, user_id)
            .filter(EncounterRepository._ended())
            .order_by("-start_time")[:limit]
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def update(pk: int, data: EncounterData) -> None:
        encounter = Encounter.objects.get(pk=pk)
        save_replacing_files(encounter, data)

    @staticmethod
    def delete(pk: int) -> None:
        Encounter.objects.filter(pk=pk).delete()


class EncounterRSVPRepository(EncounterRSVPRepositoryProtocol):
    @staticmethod
    def create(
        encounter_id: int, ip_address: str | None, user_id: int
    ) -> EncounterRSVPDTO:
        rsvp = EncounterRSVP.objects.create(
            encounter_id=encounter_id, ip_address=ip_address, user_id=user_id
        )
        return EncounterRSVPDTO.model_validate(rsvp)

    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterRSVPDTO]:
        rsvps = EncounterRSVP.objects.filter(encounter_id=encounter_id).order_by(
            "creation_time"
        )
        return [EncounterRSVPDTO.model_validate(r) for r in rsvps]

    @staticmethod
    def count_by_encounter(encounter_id: int) -> int:
        return EncounterRSVP.objects.filter(encounter_id=encounter_id).count()

    @staticmethod
    def count_by_encounters(encounter_ids: list[int]) -> dict[int, int]:
        rows = (
            EncounterRSVP.objects.filter(encounter_id__in=encounter_ids)
            .values("encounter_id")
            .annotate(total=Count("pk"))
        )
        return {row["encounter_id"]: row["total"] for row in rows}

    @staticmethod
    def recent_rsvp_exists(ip_address: str, seconds: int = 60) -> bool:
        cutoff = datetime.now(tz=UTC) - timedelta(seconds=seconds)
        return EncounterRSVP.objects.filter(
            ip_address=ip_address, creation_time__gte=cutoff
        ).exists()

    @staticmethod
    def user_has_rsvpd(encounter_id: int, user_id: int) -> bool:
        return EncounterRSVP.objects.filter(
            encounter_id=encounter_id, user_id=user_id
        ).exists()

    @staticmethod
    def delete_by_user(encounter_id: int, user_id: int) -> None:
        EncounterRSVP.objects.filter(
            encounter_id=encounter_id, user_id=user_id
        ).delete()


def _active_account() -> QuerySet[User]:
    return User.objects.filter(
        email__iexact=OuterRef("email"), user_type=UserType.ACTIVE
    )


class EncounterInviteeRepository(EncounterInviteeRepositoryProtocol):
    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterInviteeDTO]:
        rows = (
            EncounterInvitee.objects.filter(encounter_id=encounter_id)
            .exclude(status=InviteeStatus.REMOVED)
            .annotate(user_id=Subquery(_active_account().values("pk")[:1]))
            .order_by("creation_time", "pk")
        )
        return [EncounterInviteeDTO.model_validate(row) for row in rows]

    @staticmethod
    def add(encounter_id: int, emails: list[str]) -> None:
        EncounterInvitee.objects.filter(
            encounter_id=encounter_id, email__in=emails, status=InviteeStatus.REMOVED
        ).update(status=InviteeStatus.INVITED)
        EncounterInvitee.objects.bulk_create(
            [EncounterInvitee(encounter_id=encounter_id, email=e) for e in emails],
            ignore_conflicts=True,
        )

    @staticmethod
    def remove(encounter_id: int, emails: list[str]) -> None:
        EncounterInvitee.objects.filter(
            encounter_id=encounter_id, email__in=emails
        ).update(status=InviteeStatus.REMOVED)

    @staticmethod
    def set_status(*, encounter_id: int, email: str, status: InviteeStatus) -> bool:
        updated = (
            EncounterInvitee.objects.filter(
                encounter_id=encounter_id, email__iexact=email
            )
            .exclude(status=InviteeStatus.REMOVED)
            .update(status=status)
        )
        return updated > 0

    @staticmethod
    def read_status(encounter_id: int, email: str) -> InviteeStatus | None:
        status = (
            EncounterInvitee.objects.filter(
                encounter_id=encounter_id, email__iexact=email
            )
            .values_list("status", flat=True)
            .first()
        )
        return InviteeStatus(status) if status else None

    @staticmethod
    def count_accepted_without_account(encounter_id: int) -> int:
        return (
            EncounterInvitee.objects.filter(
                encounter_id=encounter_id, status=InviteeStatus.ACCEPTED
            )
            .exclude(Exists(_active_account()))
            .count()
        )

    @staticmethod
    def count_invited_by_creator_since(creator_id: int, since: datetime) -> int:
        return EncounterInvitee.objects.filter(
            encounter__creator_id=creator_id, creation_time__gte=since
        ).count()
