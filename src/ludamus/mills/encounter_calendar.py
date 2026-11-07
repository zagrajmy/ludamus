"""Who holds an encounter in their calendar, and the invites that keep it so.

An encounter's guests are its creator, everyone signed up, and everyone the
creator invited by email who has not declined. Each change mails the guests
it touches an iTIP message with the same UID, so their calendar entry
follows the encounter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from ludamus.pacts.calendar import PartStat
from ludamus.pacts.encounter import (
    EncounterInvite,
    EncounterInviteReason,
    InviteeStatus,
    InviteLimitError,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.specs.encounter import (
    CALENDAR_MAILS_PER_CREATOR_PER_DAY,
    CALENDAR_MAILS_PER_NEW_CREATOR_PER_DAY,
    ENCOUNTER_DEFAULT_DURATION,
    ENCOUNTER_RSVP_THROTTLE_SECONDS,
    INVITEE_WINDOW,
    INVITEES_PER_CREATOR_PER_DAY,
    INVITEES_PER_NEW_CREATOR_PER_DAY,
    NEW_CREATOR_AGE,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.encounter import (
        EncounterDTO,
        EncounterInviteeRepositoryProtocol,
        EncounterInviteMailerProtocol,
        EncounterRSVPRepositoryProtocol,
    )
    from ludamus.pacts.legacy import CacheProtocol
    from ludamus.pacts.multiverse import SitesServiceProtocol


logger = logging.getLogger(__name__)

_UID_DOMAIN = "@ludamus"
# NOTE: what a creator mails invitees on their own initiative, as often as
# they edit. Signups chose to hear and the creator's own copy is theirs, so
# only invitees count; a cancellation is never held back.
_CHARGED = frozenset({EncounterInviteReason.INVITED, EncounterInviteReason.CHANGED})
_INVITEE_PARTSTAT = {
    InviteeStatus.INVITED: PartStat.NEEDS_ACTION,
    InviteeStatus.ACCEPTED: PartStat.ACCEPTED,
}


def encounter_calendar_uid(share_code: str) -> str:
    return f"{share_code}{_UID_DOMAIN}"


def encounter_share_code(uid: str) -> str:
    return uid.removesuffix(_UID_DOMAIN) if uid.endswith(_UID_DOMAIN) else ""


@dataclass(frozen=True)
class Guest:
    email: str
    name: str
    partstat: PartStat
    invited_only: bool = False
    asks_reply: bool = True


def guest_for(user: UserDTO, *, asks_reply: bool = True) -> Guest:
    return Guest(
        email=user.email.lower(),
        name=user.name,
        partstat=PartStat.ACCEPTED,
        asks_reply=asks_reply,
    )


def _normalised(emails: Iterable[str], *, excluding: str) -> set[str]:
    return {e.strip().lower() for e in emails if e.strip()} - {excluding.lower()}


class EncounterGuests:
    """The one place that changes who holds an encounter in their calendar.

    Signing up on the site and accepting from a calendar both go through
    `admit`; leaving and declining both go through `release`. `invitees` is
    the invitee repository itself, for reads that need nothing more.
    """

    def __init__(
        self,
        *,
        rsvps: EncounterRSVPRepositoryProtocol,
        invitees: EncounterInviteeRepositoryProtocol,
        users: UserRepositoryProtocol,
        sites: SitesServiceProtocol,
        mailer: EncounterInviteMailerProtocol,
        cache: CacheProtocol,
    ) -> None:
        self._rsvps = rsvps
        self.invitees = invitees
        self._users = users
        self._sites = sites
        self._mailer = mailer
        self._cache = cache

    def recently_rsvpd(self, ip_address: str) -> bool:
        # The address lives in the cache for the length of the window and
        # nowhere else. Reserving it here rather than reading a stored IP is
        # what keeps the throttle from needing a column that outlives it.
        key = f"encounter_rsvp_rate:{sha256(ip_address.encode()).hexdigest()}"
        if self._cache.get(key) is not None:
            return True
        self._cache.set(key, 1, timeout=ENCOUNTER_RSVP_THROTTLE_SECONDS)
        return False

    def has_room(self, encounter: EncounterDTO, *, email: str) -> bool:
        if not (limit := encounter.max_participants):
            return True
        # NOTE: an invitee who accepted already holds a spot; signing up
        # turns that spot into a signup rather than taking a second one.
        if self.invitees.read_status(encounter.pk, email) is InviteeStatus.ACCEPTED:
            return True
        taken = self._rsvps.count_by_encounter(encounter.pk)
        return taken + self.invitees.count_accepted_without_signup(encounter.pk) < limit

    def admit(
        self, encounter: EncounterDTO, *, email: str, user: UserDTO | None
    ) -> bool:
        """Take a spot for `email`: a signup for an account, else the invite.

        Returns:
            False, writing nothing, when the encounter has no room.
        """
        if not self.has_room(encounter, email=email):
            return False
        if user is not None:
            self._rsvps.create(encounter.pk, user.pk)
        self.invitees.set_status(
            encounter_id=encounter.pk, email=email, status=InviteeStatus.ACCEPTED
        )
        return True

    def release(
        self, encounter: EncounterDTO, *, email: str, user: UserDTO | None
    ) -> bool:
        """Give up `email`'s spot: drop the signup, mark the invite declined.

        Returns:
            Whether there was a signup or an invite to give up.
        """
        signed_up = user is not None and self._rsvps.user_has_rsvpd(
            encounter.pk, user.pk
        )
        if signed_up and user is not None:
            self._rsvps.delete_by_user(encounter.pk, user.pk)
        declined = self.invitees.set_status(
            encounter_id=encounter.pk, email=email, status=InviteeStatus.DECLINED
        )
        return signed_up or declined

    def replace_invitees(
        self, encounter: EncounterDTO, emails: Iterable[str], *, creator: UserDTO
    ) -> set[str]:
        """Make the invitee list `emails`; mail the removed a cancellation.

        Returns:
            The addresses newly invited, whose invite the caller sends once
            the encounter itself is settled.

        Raises:
            InviteLimitError: the new addresses would take the creator past
                the daily limit. Nothing is written.
        """
        wanted = _normalised(emails, excluding=creator.email)
        current = {i.email for i in self.invitees.list_by_encounter(encounter.pk)}
        added = wanted - current
        now = datetime.now(tz=UTC)
        # NOTE: two saves racing past this read can each stay under the cap
        # and together exceed it, by at most one form's worth of addresses.
        counted = self.invitees.emails_invited_by_creator_since(
            creator.pk, now - INVITEE_WINDOW
        )
        new = added - counted
        limit = (
            INVITEES_PER_NEW_CREATOR_PER_DAY
            if _is_new(creator, now)
            else INVITEES_PER_CREATOR_PER_DAY
        )
        if new and len(counted) + len(new) > limit:
            logger.warning(
                "Encounter %s: creator %s hit the daily invite limit (%d + %d > %d)",
                encounter.share_code,
                creator.pk,
                len(counted),
                len(new),
                limit,
            )
            raise InviteLimitError
        removed = current - wanted
        dropped = [
            g for g in self.guests(encounter) if g.email in removed and g.invited_only
        ]
        self.invitees.remove(encounter.pk, sorted(removed))
        self.invitees.add(
            encounter_id=encounter.pk, emails=sorted(added), creator_id=creator.pk
        )
        self.send(encounter, reason=EncounterInviteReason.UNINVITED, guests=dropped)
        return added

    def guests(self, encounter: EncounterDTO) -> list[Guest]:
        member_ids = [encounter.creator_id] + [
            rsvp.user_id for rsvp in self._rsvps.list_by_encounter(encounter.pk)
        ]
        invitees = self.invitees.list_by_encounter(encounter.pk)
        account_ids = [i.user_id for i in invitees if i.user_id is not None]
        users: dict[int, UserDTO] = {
            int(u.pk): u
            for u in self._users.read_by_ids(sorted({*member_ids, *account_ids}))
        }
        by_email: dict[str, Guest] = {}
        for user_id in member_ids:
            if (user := users.get(user_id)) and user.email:
                by_email.setdefault(
                    user.email.lower(),
                    guest_for(user, asks_reply=user_id != encounter.creator_id),
                )
        for invitee in invitees:
            if invitee.status not in _INVITEE_PARTSTAT:
                continue
            # pragma: no mutate start
            account = users.get(invitee.user_id) if invitee.user_id else None
            # pragma: no mutate end
            by_email.setdefault(
                invitee.email,
                Guest(
                    email=invitee.email,
                    name=account.name if account else "",
                    partstat=_INVITEE_PARTSTAT[invitee.status],
                    invited_only=True,
                ),
            )
        return list(by_email.values())

    def send(
        self,
        encounter: EncounterDTO,
        *,
        reason: EncounterInviteReason,
        guests: list[Guest],
    ) -> None:
        if not guests:
            return
        sphere = self._sites.read(encounter.sphere_id)
        try:
            creator: UserDTO | None = self._users.read_by_id(encounter.creator_id)
        except NotFoundError:
            creator = None
        if creator is not None and reason in _CHARGED:
            self._charge(creator, sum(guest.invited_only for guest in guests))
        # NOTE: iTIP applies the message with the highest SEQUENCE per UID. A
        # clock reading rises across edits without a stored counter, within
        # limits: sends in the same second tie (clients then compare
        # DTSTAMP), worker clock skew can step back, and it outgrows the
        # int32 RFC 5545 INTEGER in 2038.
        sequence = int(datetime.now(tz=UTC).timestamp())  # pragma: no mutate
        self._mailer.send(
            [
                EncounterInvite(
                    reason=reason,
                    partstat=guest.partstat,
                    asks_reply=guest.asks_reply,
                    uid=encounter_calendar_uid(encounter.share_code),
                    sequence=sequence,
                    encounter=encounter,
                    end_time=encounter.end_time
                    or encounter.start_time + ENCOUNTER_DEFAULT_DURATION,
                    organizer_name=(creator.name if creator else "") or sphere.name,
                    attendee_name=guest.name,
                    attendee_email=guest.email,
                    sphere_domain=sphere.site.domain,
                )
                for guest in guests
            ]
        )

    def _charge(self, creator: UserDTO, count: int) -> None:
        """Count `count` invitee messages against the creator's daily budget.

        Raises:
            InviteLimitError: the messages would take the creator past the
                budget for the last day. Nothing is counted.
        """
        if not count:
            return
        now = datetime.now(tz=UTC)
        spent = self.invitees.count_mailed_since(creator.pk, now - INVITEE_WINDOW)
        budget = (
            CALENDAR_MAILS_PER_NEW_CREATOR_PER_DAY
            if _is_new(creator, now)
            else CALENDAR_MAILS_PER_CREATOR_PER_DAY
        )
        if spent + count > budget:
            logger.warning(
                "Creator %s hit the daily calendar mail budget (%d + %d > %d)",
                creator.pk,
                spent,
                count,
                budget,
            )
            raise InviteLimitError
        self.invitees.record_mailing(creator_id=creator.pk, count=count)


def _is_new(creator: UserDTO, now: datetime) -> bool:
    return now - creator.date_joined < NEW_CREATOR_AGE
