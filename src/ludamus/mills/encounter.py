from __future__ import annotations

import logging
from contextlib import suppress
from hashlib import sha256
from typing import TYPE_CHECKING

from ludamus.mills.encounter_calendar import guest_for
from ludamus.pacts.encounter import (
    PAST_FEED_LIMIT,
    EncounterDetailContextDTO,
    EncounterFeed,
    EncounterIndexItem,
    EncounterInviteReason,
    EncounterServiceProtocol,
    EncountersPolicy,
    RSVPOutcome,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.multiverse import SphereRole
from ludamus.specs.encounter import (
    ENCOUNTER_RSVP_THROTTLE_SECONDS,
    INVITEE_RETENTION_AFTER_END,
    INVITEE_WINDOW,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.mills.encounter_calendar import EncounterGuests
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.encounter import (
        EncounterData,
        EncounterDTO,
        EncounterInviteeDTO,
        EncounterRepositoryProtocol,
        EncounterRSVPRepositoryProtocol,
    )
    from ludamus.pacts.legacy import CacheProtocol, SphereRepositoryProtocol
    from ludamus.pacts.multiverse import SitesServiceProtocol
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


# The feed renders every past encounter as a card, and a sphere accumulates
# them without bound. A few grid rows is what anyone scrolls back through.
class EncounterService(EncounterServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        encounters: EncounterRepositoryProtocol,
        rsvps: EncounterRSVPRepositoryProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
        sites: SitesServiceProtocol,
        guests: EncounterGuests,
        cache: CacheProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users
        self._spheres = spheres
        # Read through the sites service, not the repository: every encounter
        # route asks for the policy twice — once at the view's gate, once in
        # the method the view then calls — and that service already memoises
        # the current sphere for the request.
        self._sites = sites
        self._guests = guests
        self._cache = cache

    def _policy(self, sphere_id: int) -> EncountersPolicy:
        return self._sites.read(sphere_id).encounters_policy

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
            upcoming=self._upcoming(sphere_id=sphere_id, user_id=user_id, limit=None),
            past=self._index_items(
                self._encounters.list_visible_past(
                    sphere_id, user_id, limit=PAST_FEED_LIMIT
                ),
                user_id=user_id,
            ),
        )

    def list_upcoming(
        self, *, sphere_id: int, user_id: int | None, limit: int
    ) -> list[EncounterIndexItem]:
        """List the soonest encounters this visitor may see, at most ``limit``.

        Returns:
            The first ``limit`` upcoming encounters of the feed, soonest
            first; empty on a sphere with encounters off.
        """
        if not self.enabled(sphere_id):
            return []
        return self._upcoming(sphere_id=sphere_id, user_id=user_id, limit=limit)

    def _upcoming(
        self, *, sphere_id: int, user_id: int | None, limit: int | None
    ) -> list[EncounterIndexItem]:
        return self._index_items(
            self._encounters.list_visible_upcoming(sphere_id, user_id, limit=limit),
            user_id=user_id,
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
                organizer_name=names.get(encounter.creator_id, ""),
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
        is_creator = current_user_id == encounter.creator_id
        return EncounterDetailContextDTO(
            encounter=encounter,
            creator=creator,
            attendees=attendees,
            rsvp_count=len(rsvps),
            is_creator=is_creator,
            user_has_rsvpd=user_has_rsvpd,
            invitees=(
                self._guests.invitees.list_by_encounter(encounter.pk)
                if is_creator
                else []
            ),
            accepted_guest_count=(
                self._guests.invitees.count_accepted_without_signup(encounter.pk)
            ),
        )

    def read_by_share_code(self, *, share_code: str, sphere_id: int) -> EncounterDTO:
        return self._encounters.read_by_share_code(share_code, sphere_id)

    def create(self, data: EncounterData, *, invitee_emails: list[str]) -> EncounterDTO:
        # Creating is the one thing the policy decides, so it is checked here
        # too rather than only at the view's gate. Editing, deleting and
        # RSVPing ask about ownership or an invitation instead, and the
        # methods below answer that.
        if not self.can_create(sphere_id=data["sphere_id"], user_id=data["creator_id"]):
            raise NotFoundError
        with self._transaction.atomic():
            encounter = self._encounters.create(data)
            creator = self._users.read_by_id(encounter.creator_id)
            added = self._guests.replace_invitees(
                encounter, invitee_emails, creator=creator
            )
            self._guests.send(
                encounter,
                reason=EncounterInviteReason.CREATED,
                guests=[guest_for(creator, asks_reply=False)],
            )
            self._send_invited(encounter, added)
            return encounter

    def _send_invited(self, encounter: EncounterDTO, emails: set[str]) -> None:
        self._guests.send(
            encounter,
            reason=EncounterInviteReason.INVITED,
            guests=[g for g in self._guests.guests(encounter) if g.email in emails],
        )

    def read_owned(self, *, pk: int, sphere_id: int, user_id: int) -> EncounterDTO:
        encounter = self._encounters.read(pk, sphere_id)
        if encounter.creator_id != user_id:
            raise NotFoundError
        return encounter

    def read_owned_with_invitees(
        self, *, pk: int, sphere_id: int, user_id: int
    ) -> tuple[EncounterDTO, list[EncounterInviteeDTO]]:
        encounter = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
        return encounter, self._guests.invitees.list_by_encounter(pk)

    def update_owned(
        self,
        *,
        pk: int,
        sphere_id: int,
        user_id: int,
        data: EncounterData,
        invitee_emails: list[str],
    ) -> EncounterDTO:
        with self._transaction.atomic():
            before = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            may_create = self.can_create(sphere_id=sphere_id, user_id=user_id)
            if "is_public" in data and not may_create:
                # Owning an encounter is enough to edit it, but not to list
                # it: publishing is what the sphere's policy governs. The key
                # is dropped rather than forced false, so a sphere narrowing
                # to managers never silently unpublishes what is already out.
                data = _without_public_flag(data)
            self._encounters.update(pk, data)
            encounter = self._encounters.read(pk, sphere_id)
            # NOTE: inviting mails strangers from our domain, so it follows
            # the policy that governs creating, like publishing does.
            added = (
                self._guests.replace_invitees(
                    encounter,
                    invitee_emails,
                    creator=self._users.read_by_id(encounter.creator_id),
                )
                if may_create
                else set()
            )
            if _calendar_view(encounter) != _calendar_view(before):
                self._guests.send(
                    encounter,
                    reason=EncounterInviteReason.CHANGED,
                    guests=[
                        g
                        for g in self._guests.guests(encounter)
                        if g.email not in added
                    ],
                )
            self._send_invited(encounter, added)
            return encounter

    def delete_owned(self, *, pk: int, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            encounter = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            # NOTE: read before the delete; signups and invitees cascade away
            # with it.
            guests = self._guests.guests(encounter)
            self._encounters.delete(pk)
            self._guests.send(
                encounter, reason=EncounterInviteReason.DELETED, guests=guests
            )

    def rsvp(
        self, *, share_code: str, sphere_id: int, user_id: int, ip_address: str
    ) -> RSVPOutcome:
        # atomic() groups the checks and the insert in one transaction but
        # does not serialize concurrent signups: two requests can both pass
        # the capacity check and overshoot max_participants. Full enforcement
        # needs a row lock (select_for_update) on the encounter, which needs
        # a repo method in pacts/encounter.py — held by open PRs.
        with self._transaction.atomic():
            encounter = self._encounters.read_by_share_code(share_code, sphere_id)
            if self._recently_rsvpd(ip_address):
                return RSVPOutcome.THROTTLED
            if self._rsvps.user_has_rsvpd(encounter.pk, user_id):
                return RSVPOutcome.ALREADY_SIGNED_UP
            user = self._users.read_by_id(user_id)
            if not self._guests.admit(encounter, email=user.email, user=user):
                return RSVPOutcome.FULL
            self._guests.send(
                encounter, reason=EncounterInviteReason.JOINED, guests=[guest_for(user)]
            )
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
        with self._transaction.atomic():
            encounter = self._encounters.read_by_share_code(share_code, sphere_id)
            if not self._rsvps.user_has_rsvpd(encounter.pk, user_id):
                return
            user = self._users.read_by_id(user_id)
            self._guests.release(encounter, email=user.email, user=user)
            self._guests.send(
                encounter, reason=EncounterInviteReason.LEFT, guests=[guest_for(user)]
            )

    def purge_stale_invitees(self, *, now: datetime) -> int:
        # NOTE: a removed invitee, or one of a deleted encounter, stays only
        # as long as the daily invite cap still counts it; the rest go a
        # while after their encounter ends.
        purged = self._guests.invitees.purge_stale(
            created_before=now - INVITEE_WINDOW,
            ended_before=now - INVITEE_RETENTION_AFTER_END,
        )
        logger.info("Purged %d stale encounter invitee(s)", purged)
        return purged


def _calendar_view(
    encounter: EncounterDTO,
) -> tuple[str, str, datetime, datetime | None, str]:
    # NOTE: only what a guest's calendar shows; a capacity or cover change is
    # no reason to mail everyone.
    return (
        encounter.title,
        encounter.description,
        encounter.start_time,
        encounter.end_time,
        encounter.place,
    )


def _without_public_flag(data: EncounterData) -> EncounterData:
    # A copy, not a `del`: the caller built this dict and keeps using it, so a
    # mill reaching back into it would be an argument side effect.
    filtered = data.copy()
    filtered.pop("is_public")
    return filtered
