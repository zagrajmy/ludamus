"""A member enrolling themselves, their companions and their party's members.

Reads the enroll page (who the viewer acts for and the moves each person
has), answers the pass-allowance question the form asks before any lock, and
applies a submit: cancellations, seats, waiting-list places, held seats for
members who must accept, and +N guests, in one transaction that decides its
seats through `SeatDesk`. Notifications and the refill of freed seats follow
the commit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ludamus.mills.enrollment_member_options import (
    can_join_waitlist,
    person_field,
    skip_reason,
)
from ludamus.mills.enrollment_seats import SeatDesk
from ludamus.mills.enrollment_windows import EnrollmentPolicy, restricts_everyone
from ludamus.pacts.enrollment import (
    OCCUPYING_PARTICIPATION_STATUSES,
    SeatHoldRequest,
    SessionParticipationStatus,
    SessionSeatingDTO,
)
from ludamus.pacts.enrollment_member import (
    INCLUDE_VALUE,
    AccessProblem,
    AllowanceRefusal,
    AllowanceSpentError,
    EnrollFooterDTO,
    EnrollmentChoice,
    EnrollRefusal,
    MemberEnrollError,
    MemberEnrollErrorCode,
    MemberEnrollmentServiceProtocol,
    MemberEnrollOutcome,
    MemberEnrollPageDTO,
    NothingToChangeError,
    PartyMemberFlags,
    RosterMember,
    SeatsShortError,
    SessionUserParticipationData,
    SkippedPerson,
    SkipReason,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.ids import EventId, SessionId, UserId
from ludamus.pacts.party import PartyConsentMode, PartyEnrolledNotification
from ludamus.pacts.party import PartyMembershipStatus as MembershipStatus

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import (
        EnrollmentServiceProtocol,
        EnrollmentWindowSnapshot,
        VirtualEnrollmentConfig,
        WaitlistPromotionServiceProtocol,
    )
    from ludamus.pacts.enrollment_member import (
        EnrollSessionDTO,
        MemberEnrollmentRepositoryProtocol,
        MemberEnrollQuery,
        MemberEnrollSubmission,
    )
    from ludamus.pacts.event import EventDTO
    from ludamus.pacts.party import PartyServiceProtocol, SelectedEnrollmentPartyDTO
    from ludamus.pacts.safety import EventBanServiceProtocol, ShadowbanServiceProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.user import UserDTO

logger = logging.getLogger(__name__)

_STATUS_BY_CHOICE = {
    EnrollmentChoice.ENROLL: SessionParticipationStatus.CONFIRMED,
    EnrollmentChoice.WAITLIST: SessionParticipationStatus.WAITING,
}
# Someone holding one of these is in already: a ticked box leaves them be.
_CURRENTLY_IN = frozenset(
    {
        SessionParticipationStatus.CONFIRMED,
        SessionParticipationStatus.WAITING,
        SessionParticipationStatus.OFFERED,
    }
)


@dataclass(frozen=True)
class MemberEnrollmentPeers:
    # The services a submit reaches past its own seats: the pass accounting,
    # the held-seat and refill machinery, and who must be told or kept out.
    enrollment: EnrollmentServiceProtocol
    waitlist_promotion: WaitlistPromotionServiceProtocol
    shadowban: ShadowbanServiceProtocol
    parties: PartyServiceProtocol
    event_bans: EventBanServiceProtocol


@dataclass(frozen=True)
class _Request:
    user: UserDTO
    choice: EnrollmentChoice
    # A real co-member of the selected party: told about seats taken for them.
    is_party_member: bool = False
    needs_accept: bool = False


@dataclass
class _Batch:
    outcome: MemberEnrollOutcome = field(default_factory=MemberEnrollOutcome)
    freed_seat: bool = False
    signed_up: list[tuple[UserId, str]] = field(default_factory=list)
    held: list[UserDTO] = field(default_factory=list)
    enrolled_members: list[UserDTO] = field(default_factory=list)


class MemberEnrollmentService(MemberEnrollmentServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repository: MemberEnrollmentRepositoryProtocol,
        peers: MemberEnrollmentPeers,
    ) -> None:
        self._transaction = transaction
        self._repository = repository
        self._seats = SeatDesk(repository)
        self._peers = peers

    def read_page(self, query: MemberEnrollQuery) -> MemberEnrollPageDTO:
        session = self._read_session(query)
        parties = self._peers.parties.enrollment_selection(
            viewer_pk=query.viewer_id, requested_party=query.requested_party
        )
        if parties.requested_invalid:
            raise MemberEnrollError(MemberEnrollErrorCode.INVALID_PARTY)
        enrollment = self._peers.enrollment
        viewer = enrollment.read_viewer(query.viewer_slug)
        members = self._party_members(session, parties.selected)
        member_pks = frozenset(member.user.pk for member in members)
        household = (
            RosterMember(user=viewer),
            *(RosterMember(user=user) for user in parties.companions),
            *members,
        )
        user_ids: list[int] = [member.user.pk for member in household]
        statuses = self._repository.read_statuses(
            session_id=session.pk, user_ids=user_ids
        )
        conflicted = frozenset(
            self._repository.conflicted_user_ids(
                session_id=session.pk, user_ids=user_ids
            )
        )
        viewer_config = enrollment.virtual_config(
            event=session.event, user_email=viewer.email
        )
        # A config row with no slots left is not "configured": the predicate
        # has_slot_access applies, so every message agrees with the policy.
        is_configured = bool(viewer_config and viewer_config.allowed_slots)
        policy = EnrollmentPolicy.for_actor(
            session.eligible_windows, is_configured_user=is_configured
        )
        waitlisted = self._repository.waitlist_counts(
            event_id=session.event.pk, user_ids=user_ids
        )
        restricted_out = bool(session.eligible_windows) and not policy.can_enroll
        return MemberEnrollPageDTO(
            session=session,
            viewer=viewer,
            parties=parties,
            household=household,
            fields=tuple(
                person_field(
                    member,
                    is_member=member.user.pk in member_pks,
                    status=statuses.get(member.user.pk),
                    has_conflict=member.user.pk in conflicted,
                    can_enroll=policy.can_enroll,
                    can_join_wl=can_join_waitlist(
                        policy, waiting=waitlisted.get(member.user.pk, 0)
                    ),
                    restricted_out=restricted_out,
                )
                for member in household
            ),
            user_data=self._user_data(session, household, statuses, member_pks),
            guest_count=self._guest_count(session, viewer),
            statuses=statuses,
            conflicted_ids=conflicted,
            slot_allowance=(viewer_config if policy.requires_slot_allowance else None),
            actor_configured=bool(viewer.email) and is_configured,
            enroll_refusal=_enroll_refusal(
                restricted_out=restricted_out,
                can_enroll=policy.can_enroll,
                has_email=bool(viewer.email),
            ),
            access_problem=_access_problem(
                session, has_email=bool(viewer.email), has_config=bool(viewer_config)
            ),
        )

    def _read_session(self, query: MemberEnrollQuery) -> EnrollSessionDTO:
        try:
            session = self._repository.read_session(
                session_id=query.session_id,
                event_slug=query.event_slug,
                sphere_id=query.sphere_id,
            )
        except NotFoundError:
            raise MemberEnrollError(MemberEnrollErrorCode.SESSION_NOT_FOUND) from None
        if session.agenda_item is not None:
            if not session.is_publicly_scheduled:
                raise MemberEnrollError(MemberEnrollErrorCode.SESSION_NOT_FOUND)
        elif not self._repository.read_statuses(
            session_id=session.pk, user_ids=[query.viewer_id]
        ):
            raise MemberEnrollError(MemberEnrollErrorCode.NO_ENROLLMENT_CONFIG)
        # Hard event ban: bounce back to the (fake-full) event page without
        # revealing the ban.
        if self._peers.event_bans.is_banned(
            event_id=EventId(session.event.pk), user_id=UserId(query.viewer_id)
        ):
            raise MemberEnrollError(MemberEnrollErrorCode.BANNED)
        return session

    def _party_members(
        self, session: EnrollSessionDTO, selected: SelectedEnrollmentPartyDTO | None
    ) -> list[RosterMember]:
        # Real ACTIVE co-members of the viewer's own led party. Whether one
        # can be seated directly follows their consent (O-9): only
        # ACCEPT_INVITES members need the held-seat accept round-trip.
        if selected is None or not selected.is_own_led:
            return []
        eligible = [
            member
            for member in selected.members
            if not member.is_leader
            and not member.is_login_less
            and member.status == MembershipStatus.ACTIVE
        ]
        if not eligible:
            return []
        enrollment = self._peers.enrollment
        users = {
            user.pk: user
            for user in enrollment.read_users([member.user_pk for member in eligible])
        }
        restricted = restricts_everyone(session.eligible_windows)
        return [
            RosterMember(
                user=users[member.user_pk],
                needs_accept=member.consent_mode == PartyConsentMode.ACCEPT_INVITES,
                can_enroll=not restricted
                or enrollment.has_slot_access(
                    event=session.event, user_email=users[member.user_pk].email
                ),
            )
            for member in eligible
            if member.user_pk in users
        ]

    def _user_data(
        self,
        session: EnrollSessionDTO,
        household: tuple[RosterMember, ...],
        statuses: dict[int, str],
        member_pks: frozenset[int],
    ) -> tuple[SessionUserParticipationData, ...]:
        overlapping = self._repository.overlapping_user_ids(
            session_id=session.pk, user_ids=[member.user.pk for member in household]
        )
        rows = []
        for member in household:
            pk = member.user.pk
            flags = (
                PartyMemberFlags(
                    is_member=True,
                    needs_accept=member.needs_accept,
                    blocked=not member.can_enroll,
                )
                if pk in member_pks
                else PartyMemberFlags()
            )
            offered = statuses.get(pk) == SessionParticipationStatus.OFFERED
            rows.append(
                SessionUserParticipationData(
                    user=member.user,
                    user_enrolled=statuses.get(pk)
                    == SessionParticipationStatus.CONFIRMED,
                    user_waiting=statuses.get(pk) == SessionParticipationStatus.WAITING,
                    # An OFFERED row on a needs-accept member is a seat held for
                    # them; any other keeps the generic pending-offer treatment.
                    seat_held=offered and flags.needs_accept,
                    offer_pending=offered and not flags.needs_accept,
                    has_time_conflict=pk in overlapping,
                    membership=flags,
                )
            )
        return tuple(rows)

    def _guest_count(self, session: EnrollSessionDTO, viewer: UserDTO) -> int | None:
        # None when no open window takes anonymous seats here: the stepper
        # then never renders.
        if not any(
            window.allow_anonymous_enrollment for window in session.eligible_windows
        ):
            return None
        return self._repository.guest_count(session_id=session.pk, host_id=viewer.pk)

    def allowance_refusal(
        self, *, page: MemberEnrollPageDTO, choices: dict[int, str]
    ) -> AllowanceRefusal | None:
        if (spending := _allowance(page, choices)) is None:
            return None
        if self._passes(page.session.event, spending):
            return None
        return self._refusal(page.session.event, spending)

    def _passes(self, event: EventDTO, spending: _Spending) -> bool:
        return self._peers.enrollment.can_enroll_users(
            users=spending.payers,
            event=event,
            virtual_config=spending.passes,
            users_to_enroll=spending.newcomers,
        )

    def _refusal(self, event: EventDTO, spending: _Spending) -> AllowanceRefusal:
        enrollment = self._peers.enrollment
        first = spending.newcomers[0]
        return AllowanceRefusal(
            user_id=first.pk,
            name=first.full_name,
            used=enrollment.get_used_slots(users=spending.payers, event=event),
            allowed=spending.passes.allowed_slots,
            available=enrollment.get_vc_available_slots(
                users=spending.payers, event=event, virtual_config=spending.passes
            ),
        )

    def submit(
        self, *, page: MemberEnrollPageDTO, submission: MemberEnrollSubmission
    ) -> MemberEnrollOutcome:
        requests = (
            self._desired_requests(page, submission)
            if submission.desired
            else _explicit_requests(page, submission)
        )
        if (
            not (
                requests
                and all(req.choice == EnrollmentChoice.CANCEL for req in requests)
            )
            and not page.session.eligible_windows
        ):
            # Cancels release seats and must work with every window deleted.
            raise MemberEnrollError(MemberEnrollErrorCode.NO_ELIGIBLE_WINDOW)
        # An empty guests box leaves the headcount as it is (it is prefilled,
        # so it is only empty when cleared on purpose).
        guests_target = submission.guests if page.guest_count is not None else None
        if not requests and guests_target in {None, page.guest_count}:
            raise NothingToChangeError(
                quiet=guests_target is not None or submission.desired
            )
        with self._transaction.atomic():
            batch = self._take(page, submission, requests, guests_target)
        self._after_commit(page, batch)
        return batch.outcome

    def _desired_requests(
        self, page: MemberEnrollPageDTO, submission: MemberEnrollSubmission
    ) -> list[_Request]:
        # The full page posts one "include" box per person and lets the
        # system decide seat or waiting list.
        cancels: list[_Request] = []
        wants_in: list[RosterMember] = []
        freed = 0
        fields = {item.user.pk: item for item in page.fields}
        member_pks = _member_pks(page)
        for member in page.household:
            if not member.user.is_active:
                continue
            pk = member.user.pk
            choices = fields[pk].choices
            status = page.statuses.get(pk)
            if submission.choices.get(pk) == INCLUDE_VALUE:
                # Someone already in, or who would only be skipped for a
                # conflict, is left untouched.
                if status in _CURRENTLY_IN or pk in page.conflicted_ids:
                    continue
                if choices & {EnrollmentChoice.ENROLL, EnrollmentChoice.WAITLIST}:
                    wants_in.append(member)
            elif status in _CURRENTLY_IN and EnrollmentChoice.CANCEL in choices:
                cancels.append(_request(member, EnrollmentChoice.CANCEL, member_pks))
                freed += status in OCCUPYING_PARTICIPATION_STATUSES
        return cancels + self._route(page, wants_in, freed)

    def _route(
        self, page: MemberEnrollPageDTO, wants_in: list[RosterMember], freed: int
    ) -> list[_Request]:
        # Fill seats first in household order, overflow to the waiting list.
        session = page.session
        available = SeatDesk.room(
            self._actor_policy(page, session.eligible_windows),
            SessionSeatingDTO(
                title=session.title,
                participants_limit=session.participants_limit,
                enrolled_count=session.seats.enrolled_count,
                eligible_windows=session.eligible_windows,
            ),
            freed=freed,
        )
        fields = {item.user.pk: item for item in page.fields}
        member_pks = _member_pks(page)
        routed: list[_Request] = []
        for member in wants_in:
            choices = fields[member.user.pk].choices
            if member.needs_accept:
                # A held seat always takes a seat; there is no waiting-list
                # form of it.
                if available <= 0:
                    continue
                choice = EnrollmentChoice.ENROLL
            elif available > 0 and EnrollmentChoice.ENROLL in choices:
                choice = EnrollmentChoice.ENROLL
            elif EnrollmentChoice.WAITLIST in choices:
                choice = EnrollmentChoice.WAITLIST
            else:
                continue
            available -= choice == EnrollmentChoice.ENROLL
            routed.append(_request(member, choice, member_pks))
        return routed

    @staticmethod
    def _actor_policy(
        page: MemberEnrollPageDTO, windows: list[EnrollmentWindowSnapshot]
    ) -> EnrollmentPolicy:
        return EnrollmentPolicy.for_actor(
            windows, is_configured_user=page.actor_configured
        )

    def _take(
        self,
        page: MemberEnrollPageDTO,
        submission: MemberEnrollSubmission,
        requests: list[_Request],
        guests_target: int | None,
    ) -> _Batch:
        session_id = page.session.pk
        seating = self._seats.lock_session(session_id)
        # The guest delta comes from the absolute target under the session
        # lock, so a replayed submit is a no-op instead of more guests.
        guests_delta = (
            0
            if guests_target is None
            else guests_target
            - self._repository.guest_count(
                session_id=session_id, host_id=page.viewer.pk
            )
        )
        guests_in, guests_out = max(guests_delta, 0), max(-guests_delta, 0)
        # The viewer always: they host the guests and own the passes spent.
        self._seats.lock_people(
            session_id=session_id,
            user_ids=[page.viewer.pk, *(req.user.pk for req in requests)],
            refills=bool(guests_out)
            or any(req.choice == EnrollmentChoice.CANCEL for req in requests),
        )
        self._recheck_allowance(page, submission)
        statuses = self._repository.read_statuses(
            session_id=session_id, user_ids=[req.user.pk for req in requests]
        )
        # A request read before an earlier submit seated the same person asks
        # for what is already true. Counting them again would refuse the
        # second click for the seat the first one took.
        asked = requests
        requests = [req for req in requests if not _already_so(req, statuses)]
        if asked and not requests and not (guests_in or guests_out):
            raise NothingToChangeError(quiet=True)
        self._check_capacity(
            page,
            seating,
            requests,
            guests_in=guests_in,
            freed=guests_out
            + sum(
                req.choice == EnrollmentChoice.CANCEL
                and statuses.get(req.user.pk) in OCCUPYING_PARTICIPATION_STATUSES
                for req in requests
            ),
        )
        batch = _Batch()
        self._apply(page, seating, requests, statuses, batch)
        if guests_in or guests_out:
            self._adjust_guests(page, guests_in=guests_in, guests_out=guests_out)
            batch.freed_seat = batch.freed_seat or bool(guests_out)
            batch.outcome.guest_total = self._repository.guest_count(
                session_id=session_id, host_id=page.viewer.pk
            )
        self._hold_seats(page, seating, batch)
        return batch

    def _recheck_allowance(
        self, page: MemberEnrollPageDTO, submission: MemberEnrollSubmission
    ) -> None:
        # The form asked before any lock; this answer counts, read after every
        # other request on these passes committed.
        if (spending := _allowance(page, submission.choices)) is None:
            return
        if not self._passes(page.session.event, spending):
            logger.info(
                "Enroll into session %s refused under the lock: passes spent",
                page.session.pk,
            )
            raise AllowanceSpentError(self._refusal(page.session.event, spending))

    def _check_capacity(
        self,
        page: MemberEnrollPageDTO,
        seating: SessionSeatingDTO,
        requests: list[_Request],
        *,
        guests_in: int,
        freed: int,
    ) -> None:
        members = sum(req.choice == EnrollmentChoice.ENROLL for req in requests)
        if not (wanted := members + guests_in):
            return
        # Account holders take seats under their own windows; guests under
        # any window that can seat the session at all.
        session_policy = EnrollmentPolicy.for_actor(
            seating.eligible_windows, is_configured_user=True
        )
        available = (
            SeatDesk.room(session_policy, seating, freed=freed)
            if session_policy.can_enroll
            else freed
        )
        member_room = SeatDesk.room(
            self._actor_policy(page, seating.eligible_windows), seating, freed=freed
        )
        if members > member_room:
            raise SeatsShortError(
                requested=members, available=member_room, blame_guests=False
            )
        if wanted > available:
            raise SeatsShortError(
                requested=wanted, available=available, blame_guests=True
            )

    def _apply(
        self,
        page: MemberEnrollPageDTO,
        seating: SessionSeatingDTO,
        requests: list[_Request],
        statuses: dict[int, str],
        batch: _Batch,
    ) -> None:
        # The presenter's shadowbanned players are never seated, even by an
        # unbanned manager enrolling a banned companion.
        shadowbanned = (
            self._peers.shadowban.banned_user_ids(UserId(seating.presenter_id))
            if seating.presenter_id
            else set()
        )
        conflicted = self._repository.conflicted_user_ids(
            session_id=page.session.pk,
            user_ids=[
                req.user.pk for req in requests if req.choice == EnrollmentChoice.ENROLL
            ],
        )
        # Cancellations first: a seat freed in this batch is there for a
        # companion enrolling in the same submit.
        for req in sorted(requests, key=_cancels_first):
            if req.choice == EnrollmentChoice.CANCEL:
                self._cancel(page, req, batch)
                continue
            reason = skip_reason(
                user_id=req.user.pk,
                presenter_id=seating.presenter_id,
                shadowbanned=req.user.pk in shadowbanned,
                conflicted=req.user.pk in conflicted,
                choice=req.choice,
                holds_row=req.user.pk in statuses,
                needs_accept=req.needs_accept,
            )
            if reason is not None:
                batch.outcome.skipped.append(SkippedPerson(req.user.full_name, reason))
                continue
            self._seat(page, req, is_fresh=req.user.pk not in statuses, batch=batch)

    def _cancel(self, page: MemberEnrollPageDTO, req: _Request, batch: _Batch) -> None:
        # A racing request may have deleted the row already: skip, not fail.
        status = self._repository.release(
            session_id=page.session.pk, user_id=req.user.pk
        )
        if status is None:
            batch.outcome.skipped.append(
                SkippedPerson(req.user.full_name, SkipReason.NO_ENROLLMENT_TO_CANCEL)
            )
            return
        # A freed seat (confirmed or held) promotes the next waiter after
        # the commit.
        batch.freed_seat = (
            batch.freed_seat or status in OCCUPYING_PARTICIPATION_STATUSES
        )
        batch.outcome.cancelled.append(req.user.full_name)

    def _seat(
        self, page: MemberEnrollPageDTO, req: _Request, *, is_fresh: bool, batch: _Batch
    ) -> None:
        name = req.user.full_name
        if req.needs_accept:
            # Never seated directly: the promotion service holds the seat at
            # the end of this batch, still inside its transaction.
            batch.held.append(req.user)
            batch.signed_up.append((UserId(req.user.pk), name))
            return
        status = _STATUS_BY_CHOICE[req.choice]
        # The latest submit's grouping wins: the seat promotes with the party
        # it was (re-)enrolled through.
        self._repository.seat(
            session_id=page.session.pk,
            user_id=req.user.pk,
            status=status,
            party_id=page.party_id,
        )
        if req.is_party_member and is_fresh:
            batch.enrolled_members.append(req.user)
        (
            batch.outcome.enrolled
            if status == SessionParticipationStatus.CONFIRMED
            else batch.outcome.waitlisted
        ).append(name)
        # Only a brand-new row is a sign-up worth warning a presenter about.
        if is_fresh:
            batch.signed_up.append((UserId(req.user.pk), name))

    def _adjust_guests(
        self, page: MemberEnrollPageDTO, *, guests_in: int, guests_out: int
    ) -> None:
        if guests_in:
            self._peers.enrollment.create_guests(
                session_id=page.session.pk,
                count=guests_in,
                party_id=page.party_id,
                enrolled_by_id=page.viewer.pk,
                viewer_name=page.viewer.full_name,
            )
        if guests_out:
            # The most recent guests go, their throwaway users with them.
            self._repository.release_guests(
                session_id=page.session.pk, host_id=page.viewer.pk, count=guests_out
            )

    def _hold_seats(
        self, page: MemberEnrollPageDTO, seating: SessionSeatingDTO, batch: _Batch
    ) -> None:
        # The promotion service owns a hold (OFFERED row, claim token, expiry,
        # notification); this transaction wraps it, so the seats agree with
        # the capacity check above.
        for member in batch.held:
            self._peers.waitlist_promotion.hold_seat(
                hold=SeatHoldRequest(
                    session_id=page.session.pk,
                    session_title=seating.title,
                    user_id=member.pk,
                    party_id=page.party_id,
                    actor_name=page.viewer.full_name,
                )
            )
            batch.outcome.held.append(member.full_name)

    def _after_commit(self, page: MemberEnrollPageDTO, batch: _Batch) -> None:
        session = page.session
        # A freed seat offers or promotes the next waiter, who is told directly.
        if batch.freed_seat:
            self._peers.waitlist_promotion.fill_freed_seats(session_id=session.pk)
        self._peers.shadowban.notify_signups(
            session_id=SessionId(session.pk), signed_up=batch.signed_up
        )
        for member in batch.enrolled_members:
            self._peers.parties.announce_member_enrolled(
                PartyEnrolledNotification(
                    recipient_user_id=member.pk,
                    actor_name=page.viewer.full_name,
                    session_id=session.pk,
                    session_title=session.title,
                    event_slug=session.event.slug,
                )
            )

    def read_footer(self, *, session_id: int, viewer_id: int) -> EnrollFooterDTO:
        session_statuses = self._repository.read_statuses(
            session_id=session_id, user_ids=[viewer_id]
        )
        return EnrollFooterDTO(
            seats=self._repository.read_seats(session_id),
            viewer_status=session_statuses.get(viewer_id),
        )


@dataclass(frozen=True)
class _Spending:
    passes: VirtualEnrollmentConfig
    payers: list[UserDTO]
    newcomers: list[UserDTO]


def _allowance(page: MemberEnrollPageDTO, choices: dict[int, str]) -> _Spending | None:
    # The passes cover the viewer and the companions they sponsor; a real
    # member's seat spends that member's own. +N guests are walk-ins without
    # passes, gated by the session's capacity alone.
    if page.slot_allowance is None:
        return None
    payers = [page.viewer, *page.parties.companions]
    by_pk: dict[int, UserDTO] = {user.pk: user for user in payers}
    newcomers = [
        by_pk[pk]
        for pk, value in choices.items()
        if pk in by_pk and _is_new_seat(value, seated=pk in page.statuses)
    ]
    if not newcomers:
        return None
    return _Spending(passes=page.slot_allowance, payers=payers, newcomers=newcomers)


def _is_new_seat(value: str, *, seated: bool) -> bool:
    # An explicit "enroll" always spends a pass; a ticked box only when it
    # brings in someone holding nothing on the session yet.
    return value == EnrollmentChoice.ENROLL or (value == INCLUDE_VALUE and not seated)


def _already_so(req: _Request, statuses: dict[int, str]) -> bool:
    # A held seat is never "already so": skip_reason says why it is skipped.
    if req.needs_accept:
        return False
    status = _STATUS_BY_CHOICE.get(req.choice)
    return status is not None and statuses.get(req.user.pk) == status


def _cancels_first(req: _Request) -> bool:
    return req.choice != EnrollmentChoice.CANCEL


def _member_pks(page: MemberEnrollPageDTO) -> frozenset[int]:
    companions = len(page.parties.companions)
    return frozenset(member.user.pk for member in page.household[1 + companions :])


def _request(
    member: RosterMember, choice: EnrollmentChoice, member_pks: frozenset[int]
) -> _Request:
    return _Request(
        user=member.user,
        choice=choice,
        is_party_member=member.user.pk in member_pks,
        needs_accept=member.needs_accept,
    )


def _explicit_requests(
    page: MemberEnrollPageDTO, submission: MemberEnrollSubmission
) -> list[_Request]:
    # The one-click fragment posts an explicit action per person.
    member_pks = _member_pks(page)
    return [
        _request(member, EnrollmentChoice(choice), member_pks)
        for member in page.household
        if member.user.is_active
        and (choice := submission.choices.get(member.user.pk))
        and choice != INCLUDE_VALUE
    ]


def _enroll_refusal(
    *, restricted_out: bool, can_enroll: bool, has_email: bool
) -> EnrollRefusal | None:
    if restricted_out:
        return (
            EnrollRefusal.ACCESS_REQUIRED if has_email else EnrollRefusal.EMAIL_REQUIRED
        )
    return None if can_enroll else EnrollRefusal.NOT_AVAILABLE


def _access_problem(
    session: EnrollSessionDTO, *, has_email: bool, has_config: bool
) -> AccessProblem | None:
    if not restricts_everyone(session.eligible_windows):
        return None
    if not has_email:
        return AccessProblem.EMAIL
    return None if has_config else AccessProblem.ACCESS
