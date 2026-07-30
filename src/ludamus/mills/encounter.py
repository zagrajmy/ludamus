from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from ludamus.pacts.encounter import (
    EncounterDetailContextDTO,
    EncounterServiceProtocol,
    RSVPOutcome,
)
from ludamus.pacts.legacy import EncounterIndexItem, EncounterIndexResult, NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        EncounterData,
        EncounterDTO,
        EncounterRepositoryProtocol,
        EncounterRSVPRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class EncounterService(EncounterServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        encounters: EncounterRepositoryProtocol,
        rsvps: EncounterRSVPRepositoryProtocol,
        users: UserRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users

    def build_index(self, *, sphere_id: int, user_id: int) -> EncounterIndexResult:
        my_upcoming = self._encounters.list_upcoming_by_creator(sphere_id, user_id)
        rsvpd = self._encounters.list_upcoming_rsvpd(sphere_id, user_id)
        my_ids = {e.pk for e in my_upcoming}

        upcoming = [
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._rsvps.count_by_encounter(e.pk),
                is_mine=True,
                organizer_name="",
            )
            for e in my_upcoming
        ]
        upcoming.extend(
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._rsvps.count_by_encounter(e.pk),
                is_mine=False,
                organizer_name=self._resolve_creator_name(e.creator_id),
            )
            for e in rsvpd
            if e.pk not in my_ids
        )
        upcoming.sort(key=lambda x: x.encounter.start_time)

        past = [
            EncounterIndexItem(
                encounter=e,
                rsvp_count=self._rsvps.count_by_encounter(e.pk),
                is_mine=e.creator_id == user_id,
                organizer_name=(
                    ""
                    if e.creator_id == user_id
                    else self._resolve_creator_name(e.creator_id)
                ),
            )
            for e in self._encounters.list_past(sphere_id, user_id)
        ]

        return EncounterIndexResult(upcoming=upcoming, past=past)

    def build_detail(
        self, *, share_code: str, current_user_id: int | None
    ) -> EncounterDetailContextDTO:
        encounter = self._encounters.read_by_share_code(share_code)
        creator = self._users.read_by_id(encounter.creator_id)
        rsvps = self._rsvps.list_by_encounter(encounter.pk)
        attendees: list[UserDTO] = []
        for rsvp in rsvps:
            with suppress(NotFoundError):
                attendees.append(self._users.read_by_id(rsvp.user_id))
        rsvp_count = len(rsvps)
        user_has_rsvpd = current_user_id is not None and self._rsvps.user_has_rsvpd(
            encounter.pk, current_user_id
        )
        return EncounterDetailContextDTO(
            encounter=encounter,
            creator=creator,
            attendees=attendees,
            rsvp_count=rsvp_count,
            is_full=(
                encounter.max_participants > 0
                and rsvp_count >= encounter.max_participants
            ),
            spots_remaining=(
                max(0, encounter.max_participants - rsvp_count)
                if encounter.max_participants > 0
                else None
            ),
            is_creator=current_user_id == encounter.creator_id,
            user_has_rsvpd=user_has_rsvpd,
        )

    def read_by_share_code(self, share_code: str) -> EncounterDTO:
        return self._encounters.read_by_share_code(share_code)

    def create(self, data: EncounterData) -> EncounterDTO:
        with self._transaction.atomic():
            return self._encounters.create(data)

    def read_owned(self, *, pk: int, user_id: int) -> EncounterDTO:
        encounter = self._encounters.read(pk)
        if encounter.creator_id != user_id:
            raise NotFoundError
        return encounter

    def update_owned(self, *, pk: int, user_id: int, data: EncounterData) -> None:
        with self._transaction.atomic():
            self.read_owned(pk=pk, user_id=user_id)
            self._encounters.update(pk, data)

    def delete_owned(self, *, pk: int, user_id: int) -> None:
        with self._transaction.atomic():
            self.read_owned(pk=pk, user_id=user_id)
            self._encounters.delete(pk)

    def rsvp(self, *, share_code: str, user_id: int, ip_address: str) -> RSVPOutcome:
        encounter = self._encounters.read_by_share_code(share_code)
        rsvp_count = self._rsvps.count_by_encounter(encounter.pk)
        if encounter.max_participants > 0 and rsvp_count >= encounter.max_participants:
            return RSVPOutcome.FULL
        if self._rsvps.recent_rsvp_exists(ip_address):
            return RSVPOutcome.THROTTLED
        if self._rsvps.user_has_rsvpd(encounter.pk, user_id):
            return RSVPOutcome.ALREADY_SIGNED_UP
        with self._transaction.atomic():
            self._rsvps.create(encounter.pk, ip_address, user_id)
        return RSVPOutcome.CREATED

    def cancel_rsvp(self, *, share_code: str, user_id: int) -> None:
        encounter = self._encounters.read_by_share_code(share_code)
        with self._transaction.atomic():
            self._rsvps.delete_by_user(encounter.pk, user_id)

    def _resolve_creator_name(self, creator_id: int) -> str:
        try:
            user = self._users.read_by_id(creator_id)
        except NotFoundError:
            return ""
        return user.full_name or user.name or user.username
