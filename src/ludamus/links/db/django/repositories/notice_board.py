from datetime import UTC, datetime, timedelta

from django.db.models import Q

from ludamus.adapters.db.django.models import Encounter, EncounterRSVP
from ludamus.links.db.django.repositories.storage import delete_stored_file
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
        encounter = Encounter.objects.create(**data)
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def read(pk: int) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(pk=pk)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def read_by_share_code(share_code: str) -> EncounterDTO:
        try:
            encounter = Encounter.objects.get(share_code=share_code)
        except Encounter.DoesNotExist as exception:
            raise NotFoundError from exception
        return EncounterDTO.model_validate(encounter)

    @staticmethod
    def list_upcoming_by_creator(sphere_id: int, creator_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = Encounter.objects.filter(
            sphere_id=sphere_id, creator_id=creator_id, start_time__gte=now
        ).order_by("start_time")
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_upcoming_rsvpd(sphere_id: int, user_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = (
            Encounter.objects.filter(
                sphere_id=sphere_id, rsvps__user_id=user_id, start_time__gte=now
            )
            .exclude(creator_id=user_id)
            .order_by("start_time")
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def list_past(sphere_id: int, user_id: int) -> list[EncounterDTO]:
        now = datetime.now(tz=UTC)
        encounters = (
            Encounter.objects.filter(
                Q(creator_id=user_id) | Q(rsvps__user_id=user_id),
                sphere_id=sphere_id,
                start_time__lt=now,
            )
            .distinct()
            .order_by("-start_time")
        )
        return [EncounterDTO.model_validate(e) for e in encounters]

    @staticmethod
    def update(pk: int, data: EncounterData) -> None:
        encounter = Encounter.objects.get(pk=pk)
        old_header = encounter.header_image.name if "header_image" in data else None
        for key, value in data.items():
            setattr(encounter, key, value)
        encounter.save()
        if old_header and old_header != encounter.header_image.name:
            delete_stored_file(encounter.header_image, old_header)

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
