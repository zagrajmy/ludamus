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


# TODO(hasparus): the UoW-based EncounterService + EncounterDetailResult in
# mills/legacy.py are dead after this migration, but `from ludamus.mills
# import EncounterService` still resolves to the legacy class through the
# mills/__init__.py star-import facade. Delete both from mills/legacy.py as
# soon as the open PRs holding that file (#625/#626) land.
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
        mine = self._encounters.list_upcoming_by_creator(sphere_id, user_id)
        my_ids = {encounter.pk for encounter in mine}
        rsvpd = [
            encounter
            for encounter in self._encounters.list_upcoming_rsvpd(sphere_id, user_id)
            if encounter.pk not in my_ids
        ]
        upcoming = self._index_items([*mine, *rsvpd], user_id=user_id)
        upcoming.sort(key=lambda item: item.encounter.start_time)
        return EncounterIndexResult(
            upcoming=upcoming,
            past=self._index_items(
                self._encounters.list_past(sphere_id, user_id), user_id=user_id
            ),
        )

    def _index_items(
        self, encounters: list[EncounterDTO], *, user_id: int
    ) -> list[EncounterIndexItem]:
        items: list[EncounterIndexItem] = []
        for encounter in encounters:
            is_mine = encounter.creator_id == user_id
            items.append(
                EncounterIndexItem(
                    encounter=encounter,
                    rsvp_count=self._rsvps.count_by_encounter(encounter.pk),
                    is_mine=is_mine,
                    organizer_name=(
                        ""
                        if is_mine
                        else self._resolve_creator_name(encounter.creator_id)
                    ),
                )
            )
        return items

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
        user_has_rsvpd = current_user_id is not None and self._rsvps.user_has_rsvpd(
            encounter.pk, current_user_id
        )
        return EncounterDetailContextDTO(
            encounter=encounter,
            creator=creator,
            attendees=attendees,
            rsvp_count=len(rsvps),
            is_creator=current_user_id == encounter.creator_id,
            user_has_rsvpd=user_has_rsvpd,
        )

    def read_by_share_code(self, share_code: str) -> EncounterDTO:
        return self._encounters.read_by_share_code(share_code)

    def create(self, data: EncounterData) -> EncounterDTO:
        return self._encounters.create(data)

    def read_owned(self, *, pk: int, user_id: int) -> EncounterDTO:
        encounter = self._encounters.read(pk)
        if encounter.creator_id != user_id:
            raise NotFoundError
        return encounter

    def update_owned(
        self, *, pk: int, user_id: int, data: EncounterData
    ) -> EncounterDTO:
        with self._transaction.atomic():
            self.read_owned(pk=pk, user_id=user_id)
            self._encounters.update(pk, data)
            return self._encounters.read(pk)

    def delete_owned(self, *, pk: int, user_id: int) -> None:
        with self._transaction.atomic():
            self.read_owned(pk=pk, user_id=user_id)
            self._encounters.delete(pk)

    def rsvp(self, *, share_code: str, user_id: int, ip_address: str) -> RSVPOutcome:
        # atomic() groups the checks and the insert in one transaction but
        # does not serialize concurrent signups: two requests can both pass
        # the capacity check and overshoot max_participants. Full enforcement
        # needs a row lock (select_for_update) on the encounter, which needs
        # a repo method in pacts/legacy.py — held by open PRs.
        with self._transaction.atomic():
            encounter = self._encounters.read_by_share_code(share_code)
            rsvp_count = self._rsvps.count_by_encounter(encounter.pk)
            if (
                encounter.max_participants > 0
                and rsvp_count >= encounter.max_participants
            ):
                return RSVPOutcome.FULL
            if self._rsvps.recent_rsvp_exists(ip_address):
                return RSVPOutcome.THROTTLED
            if self._rsvps.user_has_rsvpd(encounter.pk, user_id):
                return RSVPOutcome.ALREADY_SIGNED_UP
            self._rsvps.create(encounter.pk, ip_address, user_id)
            return RSVPOutcome.CREATED

    def cancel_rsvp(self, *, share_code: str, user_id: int) -> None:
        encounter = self._encounters.read_by_share_code(share_code)
        self._rsvps.delete_by_user(encounter.pk, user_id)

    def _resolve_creator_name(self, creator_id: int) -> str:
        try:
            user = self._users.read_by_id(creator_id)
        except NotFoundError:
            return ""
        return user.full_name or user.name or user.username
