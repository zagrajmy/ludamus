"""Who holds an encounter in their calendar, and the invites that keep it so.

An encounter's guests are its creator, everyone signed up, and everyone the
creator invited by email who has not declined. Each change mails the guests
it touches an iTIP message with the same UID, so their calendar entry
follows the encounter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.mills.calendar import encounter_calendar_uid
from ludamus.pacts.calendar import InviteMethod, PartStat
from ludamus.pacts.encounter import (
    EncounterInvite,
    EncounterInviteReason,
    InviteeStatus,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.specs.encounter import ENCOUNTER_DEFAULT_DURATION

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.encounter import (
        EncounterDTO,
        EncounterInviteeDTO,
        EncounterInviteeRepositoryProtocol,
        EncounterInviteMailerProtocol,
        EncounterRSVPRepositoryProtocol,
    )
    from ludamus.pacts.multiverse import SitesServiceProtocol


_CANCELLING = frozenset(
    {
        EncounterInviteReason.LEFT,
        EncounterInviteReason.UNINVITED,
        EncounterInviteReason.DELETED,
        EncounterInviteReason.FULL,
    }
)
_INVITEE_PARTSTAT = {
    InviteeStatus.INVITED: PartStat.NEEDS_ACTION,
    InviteeStatus.ACCEPTED: PartStat.ACCEPTED,
}


@dataclass(frozen=True)
class Guest:
    email: str
    name: str
    partstat: PartStat
    # Invited by email and nothing more: no signup, not the creator.
    invited_only: bool = False


def guest_for(user: UserDTO) -> Guest:
    return Guest(email=user.email.lower(), name=user.name, partstat=PartStat.ACCEPTED)


def _normalised(emails: Iterable[str], *, excluding: str) -> set[str]:
    return {e.strip().lower() for e in emails if e.strip()} - {excluding.lower()}


class EncounterGuests:
    def __init__(
        self,
        *,
        rsvps: EncounterRSVPRepositoryProtocol,
        invitees: EncounterInviteeRepositoryProtocol,
        users: UserRepositoryProtocol,
        sites: SitesServiceProtocol,
        mailer: EncounterInviteMailerProtocol,
    ) -> None:
        self._rsvps = rsvps
        self._invitees = invitees
        self._users = users
        self._sites = sites
        self._mailer = mailer

    def invitees(self, encounter_id: int) -> list[EncounterInviteeDTO]:
        return self._invitees.list_by_encounter(encounter_id)

    def replace_invitees(
        self, encounter: EncounterDTO, emails: Iterable[str]
    ) -> set[str]:
        """Make the invitee list `emails`; mail the removed a cancellation.

        Returns:
            The addresses newly invited, whose invite the caller sends once
            the encounter itself is settled.
        """
        creator = self._users.read_by_id(encounter.creator_id)
        wanted = _normalised(emails, excluding=creator.email)
        current = {i.email for i in self.invitees(encounter.pk)}
        removed = current - wanted
        dropped = [
            g for g in self.guests(encounter) if g.email in removed and g.invited_only
        ]
        self._invitees.remove(encounter.pk, sorted(removed))
        self._invitees.add(encounter.pk, sorted(wanted - current))
        self.send(encounter, reason=EncounterInviteReason.UNINVITED, guests=dropped)
        return wanted - current

    def answer(self, encounter_id: int, email: str, status: InviteeStatus) -> bool:
        return self._invitees.set_status(encounter_id, email, status)

    def has_room(self, encounter: EncounterDTO) -> bool:
        limit = encounter.max_participants
        return limit == 0 or self._rsvps.count_by_encounter(encounter.pk) < limit

    def guests(self, encounter: EncounterDTO) -> list[Guest]:
        member_ids = [encounter.creator_id] + [
            rsvp.user_id for rsvp in self._rsvps.list_by_encounter(encounter.pk)
        ]
        invitees = self._invitees.list_by_encounter(encounter.pk)
        account_ids = [i.user_id for i in invitees if i.user_id is not None]
        users: dict[int, UserDTO] = {
            int(u.pk): u
            for u in self._users.read_by_ids(sorted({*member_ids, *account_ids}))
        }
        by_email: dict[str, Guest] = {}
        for user_id in member_ids:
            if (user := users.get(user_id)) and user.email:
                by_email.setdefault(user.email.lower(), guest_for(user))
        for invitee in invitees:
            if invitee.status is InviteeStatus.DECLINED:
                continue
            account = users.get(invitee.user_id) if invitee.user_id else None
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
            creator_name = self._users.read_by_id(encounter.creator_id).name
        except NotFoundError:
            creator_name = ""
        # NOTE: iTIP applies the message with the highest SEQUENCE per UID. A
        # clock reading rises across edits without a stored counter, within
        # limits: sends in the same second tie (clients then compare
        # DTSTAMP), worker clock skew can step back, and it outgrows the
        # int32 RFC 5545 INTEGER in 2038.
        sequence = int(datetime.now(tz=UTC).timestamp())
        method = InviteMethod.CANCEL if reason in _CANCELLING else InviteMethod.REQUEST
        self._mailer.send(
            [
                EncounterInvite(
                    reason=reason,
                    method=method,
                    partstat=guest.partstat,
                    uid=encounter_calendar_uid(encounter.share_code),
                    sequence=sequence,
                    encounter=encounter,
                    end_time=encounter.end_time
                    or encounter.start_time + ENCOUNTER_DEFAULT_DURATION,
                    organizer_name=creator_name or sphere.name,
                    attendee_name=guest.name,
                    attendee_email=guest.email,
                    sphere_domain=sphere.site.domain,
                )
                for guest in guests
            ]
        )
