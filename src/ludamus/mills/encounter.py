from __future__ import annotations

from contextlib import suppress
from hashlib import sha256
from typing import TYPE_CHECKING

from ludamus.pacts.encounter import (
    EncounterDetailContextDTO,
    EncounterServiceProtocol,
    RSVPOutcome,
)
from ludamus.pacts.legacy import (
    EncounterIndexItem,
    EncounterIndexResult,
    EncounterPublicPolicy,
    NotFoundError,
)
from ludamus.pacts.multiverse import SphereRole
from ludamus.specs.encounter import ENCOUNTER_RSVP_THROTTLE_SECONDS

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        CacheProtocol,
        EncounterData,
        EncounterDTO,
        EncounterRepositoryProtocol,
        EncounterRSVPRepositoryProtocol,
        SphereRepositoryProtocol,
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
        spheres: SphereRepositoryProtocol,
        cache: CacheProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users
        self._spheres = spheres
        self._cache = cache

    def can_set_public(self, *, sphere_id: int, user_id: int) -> bool:
        policy = self._spheres.read(sphere_id).encounter_public_policy
        if policy is EncounterPublicPolicy.EVERYONE:
            return True
        if policy is EncounterPublicPolicy.MANAGERS:
            user = self._users.read_by_id(user_id)
            role = self._spheres.manager_role(sphere_id, user.slug)
            return role is SphereRole.MANAGER
        return False

    def list_public_upcoming(self, *, sphere_id: int) -> list[EncounterIndexItem]:
        """List the sphere's public feed, which reads the same for everyone."""
        return self._index_items(
            self._encounters.list_public_upcoming(sphere_id), user_id=None
        )

    def build_index(self, *, sphere_id: int, user_id: int) -> EncounterIndexResult:
        all_public = self._encounters.list_public_upcoming(sphere_id)
        mine = self._encounters.list_upcoming_by_creator(sphere_id, user_id)
        my_ids = {encounter.pk for encounter in mine}
        rsvpd = [
            encounter
            for encounter in self._encounters.list_upcoming_rsvpd(sphere_id, user_id)
            if encounter.pk not in my_ids
        ]
        upcoming = self._index_items([*mine, *rsvpd], user_id=user_id)
        upcoming.sort(key=lambda item: item.encounter.start_time)
        personal_ids = {item.encounter.pk for item in upcoming}
        return EncounterIndexResult(
            upcoming=upcoming,
            past=self._index_items(
                self._encounters.list_past(sphere_id, user_id), user_id=user_id
            ),
            public=self._index_items(
                [e for e in all_public if e.pk not in personal_ids], user_id=user_id
            ),
        )

    def _index_items(
        self, encounters: list[EncounterDTO], *, user_id: int | None
    ) -> list[EncounterIndexItem]:
        # Both lookups are batched: the public feed is rendered for anonymous
        # visitors on every sphere with a timeline, so a query per card here
        # would be the page's cost.
        rsvp_counts = self._rsvps.count_by_encounters([e.pk for e in encounters])
        names = self._creator_names(
            {e.creator_id for e in encounters if e.creator_id != user_id}
        )
        return [
            EncounterIndexItem(
                encounter=encounter,
                rsvp_count=rsvp_counts.get(encounter.pk, 0),
                is_mine=encounter.creator_id == user_id,
                organizer_name=(
                    ""
                    if encounter.creator_id == user_id
                    else names.get(encounter.creator_id, "")
                ),
            )
            for encounter in encounters
        ]

    def _creator_names(self, creator_ids: set[int]) -> dict[int, str]:
        # A deleted creator simply drops out, and the caller falls back to "".
        return {
            user.pk: user.full_name or user.name or user.username
            for user in self._users.read_by_ids(sorted(creator_ids))
        }

    def build_detail(
        self, *, share_code: str, sphere_id: int, current_user_id: int | None
    ) -> EncounterDetailContextDTO:
        encounter = self._encounters.read_by_share_code(share_code, sphere_id)
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

    def read_by_share_code(self, *, share_code: str, sphere_id: int) -> EncounterDTO:
        return self._encounters.read_by_share_code(share_code, sphere_id)

    def create(self, data: EncounterData) -> EncounterDTO:
        # The public flag is policy-gated; a forged form value from someone
        # the sphere policy doesn't cover is dropped, not an error.
        if "is_public" in data and not self.can_set_public(
            sphere_id=data["sphere_id"], user_id=data["creator_id"]
        ):
            data = _without_public_flag(data)
        return self._encounters.create(data)

    def read_owned(self, *, pk: int, sphere_id: int, user_id: int) -> EncounterDTO:
        encounter = self._encounters.read(pk, sphere_id)
        if encounter.creator_id != user_id:
            raise NotFoundError
        return encounter

    def update_owned(
        self, *, pk: int, sphere_id: int, user_id: int, data: EncounterData
    ) -> EncounterDTO:
        with self._transaction.atomic():
            self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            # Dropping the key preserves the stored flag, so a policy flip to
            # "disabled" never silently unpublishes existing encounters.
            if "is_public" in data and not self.can_set_public(
                sphere_id=sphere_id, user_id=user_id
            ):
                data = _without_public_flag(data)
            self._encounters.update(pk, data)
            return self._encounters.read(pk, sphere_id)

    def delete_owned(self, *, pk: int, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            self._encounters.delete(pk)

    def rsvp(
        self, *, share_code: str, sphere_id: int, user_id: int, ip_address: str
    ) -> RSVPOutcome:
        # atomic() groups the checks and the insert in one transaction but
        # does not serialize concurrent signups: two requests can both pass
        # the capacity check and overshoot max_participants. Full enforcement
        # needs a row lock (select_for_update) on the encounter, which needs
        # a repo method in pacts/legacy.py — held by open PRs.
        with self._transaction.atomic():
            encounter = self._encounters.read_by_share_code(share_code, sphere_id)
            rsvp_count = self._rsvps.count_by_encounter(encounter.pk)
            if (
                encounter.max_participants > 0
                and rsvp_count >= encounter.max_participants
            ):
                return RSVPOutcome.FULL
            if self._recently_rsvpd(ip_address):
                return RSVPOutcome.THROTTLED
            if self._rsvps.user_has_rsvpd(encounter.pk, user_id):
                return RSVPOutcome.ALREADY_SIGNED_UP
            self._rsvps.create(encounter.pk, user_id)
            return RSVPOutcome.CREATED

    def _recently_rsvpd(self, ip_address: str) -> bool:
        # The address lives in the cache for the length of the window and
        # nowhere else. Reserving it here rather than reading a stored IP is
        # what keeps the throttle from needing a column that outlives it.
        key = f"encounter_rsvp_rate:{sha256(ip_address.encode()).hexdigest()}"
        if self._cache.get(key) is not None:
            return True
        self._cache.set(key, 1, timeout=ENCOUNTER_RSVP_THROTTLE_SECONDS)
        return False

    def cancel_rsvp(self, *, share_code: str, sphere_id: int, user_id: int) -> None:
        encounter = self._encounters.read_by_share_code(share_code, sphere_id)
        self._rsvps.delete_by_user(encounter.pk, user_id)


def _without_public_flag(data: EncounterData) -> EncounterData:
    # A copy, not a `del`: the caller built this dict and keeps using it, so a
    # mill reaching back into it would be an argument side effect.
    filtered = data.copy()
    filtered.pop("is_public", None)
    return filtered
