"""Party subdomain business logic. See RFC 0001.

Party CRUD and membership invites. Django-free; receives the repo protocol,
notifier, and a transaction. Companions (login-less members) keep their own
lifecycle in the companion views; this service owns the party shell
around them.
"""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts.party import (
    ENROLL_WITHOUT_PARTY,
    CompanionAddOutcome,
    DeletePartyOutcome,
    EnrollmentPartiesDTO,
    EnrollmentPartyChoiceDTO,
    EnrollmentPartyMemberDTO,
    InviteOutcome,
    PartyConsentMode,
    PartyInviteNotification,
    PartyJoinResult,
    PartyMembershipStatus,
    PartyServiceProtocol,
    SelectedEnrollmentPartyDTO,
)

if TYPE_CHECKING:
    from ludamus.pacts.party import (
        InvitablePartyDTO,
        PartiesOverviewDTO,
        PartyDTO,
        PartyEnrolledNotification,
        PartyNotifierProtocol,
        PartyRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class PartyService(PartyServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        parties: PartyRepositoryProtocol,
        notifier: PartyNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._parties = parties
        self._notifier = notifier

    def overview(self, viewer_pk: int) -> PartiesOverviewDTO:
        return self._parties.overview(viewer_pk)

    def create(self, *, leader_pk: int, name: str) -> int:
        with self._transaction.atomic():
            return self._parties.create(leader_pk=leader_pk, name=name)

    def rename(self, *, leader_pk: int, party_pk: int, name: str) -> bool:
        with self._transaction.atomic():
            return self._parties.rename(
                leader_pk=leader_pk, party_pk=party_pk, name=name
            )

    def delete(self, *, leader_pk: int, party_pk: int) -> DeletePartyOutcome:
        # A companion's identity row would be orphaned with its party, so a
        # party with companions refuses deletion instead of cascading them away.
        with self._transaction.atomic():
            if self._parties.has_companions(leader_pk=leader_pk, party_pk=party_pk):
                return DeletePartyOutcome.HAS_COMPANIONS
            if not self._parties.delete(leader_pk=leader_pk, party_pk=party_pk):
                return DeletePartyOutcome.NOT_FOUND
            return DeletePartyOutcome.DELETED

    def invite(
        self, *, member_pk: int, party_pk: int, identifier: str
    ) -> InviteOutcome:
        with self._transaction.atomic():
            lead = self._parties.read_active_member_party(
                member_pk=member_pk, party_pk=party_pk
            )
            if lead is None:
                return InviteOutcome.NO_SUCH_USER
            if not (matches := self._parties.find_invitable_users(identifier)):
                return InviteOutcome.NO_SUCH_USER
            if len(matches) > 1:
                return InviteOutcome.AMBIGUOUS_HANDLE
            user = matches[0]
            if self._parties.membership_exists(party_pk=party_pk, user_pk=user.pk):
                return InviteOutcome.ALREADY_MEMBER
            self._parties.create_invited_membership(party_pk=party_pk, user_pk=user.pk)
            self._notifier.notify_party_invited(
                PartyInviteNotification(
                    recipient_user_id=user.pk,
                    recipient_email=user.email,
                    party_name=lead.name,
                    leader_name=lead.leader_name,
                )
            )
            return InviteOutcome.INVITED

    def add_companion(
        self, *, member_pk: int, party_pk: int, display_name: str
    ) -> CompanionAddOutcome:
        with self._transaction.atomic():
            if (
                self._parties.read_active_member_party(
                    member_pk=member_pk, party_pk=party_pk
                )
                is None
            ):
                return CompanionAddOutcome.NO_SUCH_COMPANION
            name = display_name.strip().casefold()
            matches = [
                companion
                for companion in self._parties.led_party_companions(
                    leader_pk=member_pk, party_pk=None
                )
                if companion.name.casefold() == name
            ]
            if not matches:
                return CompanionAddOutcome.NO_SUCH_COMPANION
            if len(matches) > 1:
                return CompanionAddOutcome.AMBIGUOUS_NAME
            companion = matches[0]
            if self._parties.membership_exists(party_pk=party_pk, user_pk=companion.pk):
                return CompanionAddOutcome.ALREADY_MEMBER
            self._parties.create_invited_membership(
                party_pk=party_pk,
                user_pk=companion.pk,
                consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
                status=PartyMembershipStatus.ACTIVE,
            )
            return CompanionAddOutcome.ADDED

    def reset_invite_link(self, *, leader_pk: int, party_pk: int) -> str | None:
        with self._transaction.atomic():
            token = token_urlsafe(32)
            if not self._parties.set_invite_token(
                leader_pk=leader_pk, party_pk=party_pk, token=token
            ):
                return None
            return token

    def read_invite_token(self, *, leader_pk: int, party_pk: int) -> str:
        return self._parties.read_invite_token(leader_pk=leader_pk, party_pk=party_pk)

    def read_invitable_party(
        self, *, token: str, viewer_pk: int
    ) -> InvitablePartyDTO | None:
        return self._parties.read_party_by_invite_token(
            token=token, viewer_pk=viewer_pk
        )

    def join_via_link(self, *, token: str, user_pk: int) -> PartyJoinResult | None:
        with self._transaction.atomic():
            return self._parties.join_via_token(token=token, user_pk=user_pk)

    def accept_invite(self, *, user_pk: int, membership_pk: int) -> bool:
        with self._transaction.atomic():
            return self._parties.accept_invite(
                membership_pk=membership_pk, user_pk=user_pk
            )

    def decline_invite(self, *, user_pk: int, membership_pk: int) -> bool:
        with self._transaction.atomic():
            return self._parties.decline_invite(
                membership_pk=membership_pk, user_pk=user_pk
            )

    def remove_member(
        self, *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None:
        with self._transaction.atomic():
            return self._parties.remove_member(
                leader_pk=leader_pk, party_pk=party_pk, membership_pk=membership_pk
            )

    def leave(self, *, user_pk: int, party_pk: int) -> bool:
        with self._transaction.atomic():
            return self._parties.leave(user_pk=user_pk, party_pk=party_pk)

    def set_my_consent(
        self, *, user_pk: int, party_pk: int, mode: PartyConsentMode
    ) -> bool:
        with self._transaction.atomic():
            return self._parties.set_consent(
                user_pk=user_pk, party_pk=party_pk, mode=mode
            )

    def announce_member_enrolled(self, notification: PartyEnrolledNotification) -> None:
        # The web layer's only port to the party notifier: called once per
        # member seated directly under power of attorney.
        self._notifier.notify_party_enrolled(notification)

    def enrollment_selection(
        self, *, viewer_pk: int, requested_party: str | None
    ) -> EnrollmentPartiesDTO:
        # The party the viewer enrolls as. An explicit ENROLL_WITHOUT_PARTY
        # means just themselves; an absent parameter defaults to their own led
        # party (else the first party they belong to); a value that is not one
        # of their parties is invalid, never silently substituted.
        parties = self._parties.overview(viewer_pk).parties
        choices = [
            EnrollmentPartyChoiceDTO(
                pk=party.pk,
                name=party.name,
                leader_name=party.leader_name,
                is_own_led=party.is_leader,
            )
            for party in parties
        ]
        if requested_party == ENROLL_WITHOUT_PARTY:
            return EnrollmentPartiesDTO(choices=choices)
        if requested_party is None:
            selected = next(
                (party for party in parties if party.is_leader),
                parties[0] if parties else None,
            )
            if selected is None:
                return EnrollmentPartiesDTO(choices=choices)
        else:
            selected = next(
                (party for party in parties if str(party.pk) == requested_party), None
            )
            if selected is None:
                return EnrollmentPartiesDTO(choices=choices, requested_invalid=True)
        return EnrollmentPartiesDTO(
            choices=choices,
            selected=_selected_party(selected),
            companions=(
                self._parties.led_party_companions(
                    leader_pk=viewer_pk, party_pk=selected.pk
                )
                if selected.is_leader
                else []
            ),
        )


def _selected_party(party: PartyDTO) -> SelectedEnrollmentPartyDTO:
    return SelectedEnrollmentPartyDTO(
        pk=party.pk,
        name=party.name,
        leader_name=party.leader_name,
        is_own_led=party.is_leader,
        members=[
            EnrollmentPartyMemberDTO(
                user_pk=member.user_pk,
                name=member.name,
                slug=member.slug,
                is_login_less=member.is_login_less,
                is_leader=member.is_leader,
                consent_mode=member.consent_mode,
                status=member.status,
            )
            for member in party.members
        ],
    )
