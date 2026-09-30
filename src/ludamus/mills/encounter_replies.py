"""Applies a guest's calendar answer to an encounter invite.

Accepting in the calendar signs an account up (or marks an invitee without
one as coming); declining removes the signup. The calendar already shows
the answer, so nothing is mailed back unless the encounter is full.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.calendar import encounter_share_code
from ludamus.mills.encounter_calendar import EncounterGuests, guest_for
from ludamus.pacts.calendar import PartStat
from ludamus.pacts.encounter import (
    EncounterInviteReason,
    EncounterReplyServiceProtocol,
    InviteeStatus,
    ReplyOutcome,
)
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts.calendar import CalendarReply
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.encounter import (
        EncounterDTO,
        EncounterInviteeRepositoryProtocol,
        EncounterInviteMailerProtocol,
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
        invitees: EncounterInviteeRepositoryProtocol,
        users: UserRepositoryProtocol,
        sites: SitesServiceProtocol,
        mailer: EncounterInviteMailerProtocol,
        reply_addresses: ReplyAddressProtocol,
    ) -> None:
        self._transaction = transaction
        self._encounters = encounters
        self._rsvps = rsvps
        self._users = users
        self._reply_addresses = reply_addresses
        self._guests = EncounterGuests(
            rsvps=rsvps, invitees=invitees, users=users, sites=sites, mailer=mailer
        )

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
            return ReplyOutcome.UNKNOWN
        try:
            user: UserDTO | None = self._users.read_by_email(reply.attendee_email)
        except NotFoundError:
            user = None
        with self._transaction.atomic():
            match reply.partstat:
                case PartStat.ACCEPTED:
                    return self._accept(encounter, reply.attendee_email, user)
                case PartStat.DECLINED:
                    return self._decline(encounter, reply.attendee_email, user)
                case _:
                    return ReplyOutcome.IGNORED

    def _accept(
        self, encounter: EncounterDTO, email: str, user: UserDTO | None
    ) -> ReplyOutcome:
        if user is None:
            marked = self._guests.answer(encounter.pk, email, InviteeStatus.ACCEPTED)
            return ReplyOutcome.ACCEPTED if marked else ReplyOutcome.UNKNOWN
        if user.pk == encounter.creator_id or self._rsvps.user_has_rsvpd(
            encounter.pk, user.pk
        ):
            return ReplyOutcome.IGNORED
        if not self._guests.has_room(encounter):
            self._guests.send(
                encounter, reason=EncounterInviteReason.FULL, guests=[guest_for(user)]
            )
            return ReplyOutcome.FULL
        self._rsvps.create(encounter.pk, None, user.pk)
        self._guests.answer(encounter.pk, email, InviteeStatus.ACCEPTED)
        return ReplyOutcome.ACCEPTED

    def _decline(
        self, encounter: EncounterDTO, email: str, user: UserDTO | None
    ) -> ReplyOutcome:
        had_signup = user is not None and self._rsvps.user_has_rsvpd(
            encounter.pk, user.pk
        )
        if user is not None and had_signup:
            self._rsvps.delete_by_user(encounter.pk, user.pk)
        marked = self._guests.answer(encounter.pk, email, InviteeStatus.DECLINED)
        return ReplyOutcome.DECLINED if had_signup or marked else ReplyOutcome.UNKNOWN
