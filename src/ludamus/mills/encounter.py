from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from ludamus.pacts.encounter import (
    EncounterDetailContextDTO,
    EncounterServiceProtocol,
    RSVPOutcome,
)
from ludamus.pacts.legacy import (
    EncounterFeed,
    EncounterIndexItem,
    EncountersPolicy,
    NotFoundError,
)
from ludamus.pacts.multiverse import SphereRole

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        EncounterData,
        EncounterDTO,
        EncounterRepositoryProtocol,
        EncounterRSVPRepositoryProtocol,
        SphereRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


# The feed renders every past encounter as a card, and a sphere accumulates
# them without bound. A few grid rows is what anyone scrolls back through.
PAST_FEED_LIMIT = 24


class EncounterService(EncounterServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        encounters: EncounterRepositoryProtocol,
        rsvps: EncounterRSVPRepositoryProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users
        self._spheres = spheres
        self._policies: dict[int, EncountersPolicy] = {}

    def _policy(self, sphere_id: int) -> EncountersPolicy:
        # Memoised because the service is built per request and every
        # encounter route asks twice: once at the view's gate, once in the
        # method the view then calls.
        if sphere_id not in self._policies:
            self._policies[sphere_id] = self._spheres.read(sphere_id).encounters_policy
        return self._policies[sphere_id]

    def enabled(self, sphere_id: int) -> bool:
        return self._policy(sphere_id) is not EncountersPolicy.NONE

    def can_create(self, *, sphere_id: int, user_id: int) -> bool:
        policy = self._policy(sphere_id)
        if policy is EncountersPolicy.EVERYONE:
            return True
        if policy is EncountersPolicy.MANAGERS:
            user = self._users.read_by_id(user_id)
            role = self._spheres.manager_role(sphere_id, user.slug)
            return role is SphereRole.MANAGER
        return False

    def list_feed(self, *, sphere_id: int, user_id: int | None) -> EncounterFeed:
        """List what this visitor may see of the sphere's encounters.

        Returns:
            The listed encounters plus, for a signed-in visitor, the ones they
            organise or hold an RSVP to — upcoming soonest-first, past
            most-recent-first.
        """
        if not self.enabled(sphere_id):
            return EncounterFeed(upcoming=[], past=[])
        return EncounterFeed(
            upcoming=self._index_items(
                self._encounters.list_visible_upcoming(sphere_id, user_id),
                user_id=user_id,
            ),
            past=self._index_items(
                self._encounters.list_visible_past(sphere_id, user_id, PAST_FEED_LIMIT),
                user_id=user_id,
            ),
        )

    def _index_items(
        self, encounters: list[EncounterDTO], *, user_id: int | None
    ) -> list[EncounterIndexItem]:
        # Both lookups are batched: the public feed is rendered for anonymous
        # visitors on every sphere's events feed, so a query per card here
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
        # Enforced here and not only by the view's gate: the sphere's policy
        # is what decides the feature exists, and every caller goes through
        # this method.
        if not self.can_create(sphere_id=data["sphere_id"], user_id=data["creator_id"]):
            raise NotFoundError
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
            if self._rsvps.recent_rsvp_exists(ip_address):
                return RSVPOutcome.THROTTLED
            if self._rsvps.user_has_rsvpd(encounter.pk, user_id):
                return RSVPOutcome.ALREADY_SIGNED_UP
            self._rsvps.create(encounter.pk, ip_address, user_id)
            return RSVPOutcome.CREATED

    def cancel_rsvp(self, *, share_code: str, sphere_id: int, user_id: int) -> None:
        encounter = self._encounters.read_by_share_code(share_code, sphere_id)
        self._rsvps.delete_by_user(encounter.pk, user_id)
