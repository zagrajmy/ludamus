"""Applies a guest's calendar answer to an encounter invite.

Accepting in the calendar signs an invitee's account up, or marks an
invitee without one as coming; declining removes the signup. The calendar
already shows the answer, so nothing is mailed back unless the encounter is
full. A reply arriving after a later change on the site (a delayed accept
after leaving) still applies: iTIP replies carry no order we store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.encounter_calendar import Guest, encounter_share_code, guest_for
from ludamus.pacts.calendar import PartStat
from ludamus.pacts.encounter import (
    EncounterInviteReason,
    EncounterReplyServiceProtocol,
    EncountersPolicy,
    InviteeStatus,
    ReplyOutcome,
)
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from ludamus.mills.encounter_calendar import EncounterGuests
    from ludamus.pacts.calendar import CalendarReply
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.encounter import (
        EncounterDTO,
        EncounterRepositoryProtocol,
        EncounterRSVPRepositoryProtocol,
        ReplyAddressProtocol,
    )
    from ludamus.pacts.multiverse import SitesServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


class EncounterReplyService(EncounterReplyServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        encounters: EncounterRepositoryProtocol,
        rsvps: EncounterRSVPRepositoryProtocol,
        users: UserRepositoryProtocol,
        guests: EncounterGuests,
        reply_addresses: ReplyAddressProtocol,
        sites: SitesServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users
        self._guests = guests
        self._reply_addresses = reply_addresses
        self._sites = sites

    def apply_calendar_reply(
        self, *, address: str, reply: CalendarReply
    ) -> ReplyOutcome:
        # NOTE: the address token is the only proof the reply answers our
        # invite to this guest; it gates the sphere-free encounter lookup.
        if not self._reply_addresses.matches(
            address=address, uid=reply.uid, attendee_email=reply.attendee_email
        ):
            return ReplyOutcome.FORGED
        try:
            encounter = self._encounters.read_by_share_code_in_any_sphere(
                encounter_share_code(reply.uid)
            )
        except NotFoundError:
            return ReplyOutcome.IGNORED
        # NOTE: the site 404s every encounter route of a sphere that stopped
        # running encounters; a late calendar answer gets no further.
        policy = self._sites.read(encounter.sphere_id).encounters_policy
        if policy is EncountersPolicy.NONE:
            return ReplyOutcome.IGNORED
        try:
            user: UserDTO | None = self._users.read_by_email(reply.attendee_email)
        except NotFoundError:
            user = None
        with self._transaction.atomic():
            match reply.partstat:
                case PartStat.ACCEPTED:
                    return self._accept(
                        encounter=encounter, email=reply.attendee_email, user=user
                    )
                case PartStat.DECLINED:
                    return self._decline(
                        encounter=encounter, email=reply.attendee_email, user=user
                    )
                case _:
                    return ReplyOutcome.IGNORED

    def _accept(
        self, *, encounter: EncounterDTO, email: str, user: UserDTO | None
    ) -> ReplyOutcome:
        if user and (
            user.pk == encounter.creator_id
            or self._rsvps.user_has_rsvpd(encounter.pk, user.pk)
        ):
            return ReplyOutcome.IGNORED
        # NOTE: only an invitee still on the list may accept. Someone who
        # signed up and left, or was removed, holds an invite we cancelled.
        # Calendars also re-send an acceptance, e.g. after each update; an
        # accepted guest already holds their spot.
        status = self._guests.invitees.read_status(encounter.pk, email)
        if status not in {InviteeStatus.INVITED, InviteeStatus.DECLINED}:
            return ReplyOutcome.IGNORED
        if self._guests.admit(encounter, email=email, user=user):
            return ReplyOutcome.ACCEPTED
        guest = (
            guest_for(user)
            if user
            else Guest(email=email, name="", partstat=PartStat.NEEDS_ACTION)
        )
        self._guests.send(encounter, reason=EncounterInviteReason.FULL, guests=[guest])
        return ReplyOutcome.FULL

    def _decline(
        self, *, encounter: EncounterDTO, email: str, user: UserDTO | None
    ) -> ReplyOutcome:
        if self._guests.release(encounter, email=email, user=user):
            return ReplyOutcome.DECLINED
        return ReplyOutcome.IGNORED
