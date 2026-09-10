from datetime import UTC, datetime, timedelta

from django.db.models import Count, Q, QuerySet

from ludamus.links.db.django.models import Encounter, EncounterRSVP
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

    # What a given visitor may see of a sphere's encounters: the listed ones,
    # plus the ones they organise or hold an RSVP to. An anonymous visitor has
    # neither, so they see the listed ones alone.
    @staticmethod
    def _visible(sphere_id: int, user_id: int | None) -> QuerySet[Encounter]:
        visible = Q(is_public=True)
        if user_id is not None:
            visible |= Q(creator_id=user_id) | Q(rsvps__user_id=user_id)
        return Encounter.objects.filter(visible, sphere_id=sphere_id).distinct()

    @staticmethod
    def list_visible_upcoming(
        sphere_id: int, user_id: int | None
    ) -> list[EncounterDTO]:
        encounters = (
            EncounterRepository._visible(sphere_id, user_id)
            .filter(start_time__gte=datetime.now(tz=UTC))
            .order_by("start_time")
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_visible_past(sphere_id: int, user_id: int | None) -> list[EncounterDTO]:
        encounters = (
            EncounterRepository._visible(sphere_id, user_id)
            .filter(start_time__lt=datetime.now(tz=UTC))
            .order_by("-start_time")
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
    def create(encounter_id: int, ip_address: str, user_id: int) -> EncounterRSVPDTO:
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
