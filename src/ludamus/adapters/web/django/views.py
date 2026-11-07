import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.adapters.web.django.forms import (
    INCLUDE_VALUE,
    EnrollmentRoster,
    RosterMember,
)
from ludamus.gates.web.django.chronology.enrollment_presentation import (
    EnrollmentChoice,
    PartyMemberFlags,
    SessionUserParticipationData,
)
from ludamus.gates.web.django.chronology.event_presentation import fake_full_seats
from ludamus.gates.web.django.event.enroll_presentation import build_enroll_footer
from ludamus.links.db.django.enrollment import SeatHolderLocks
from ludamus.links.db.django.models import (
    AgendaItem,
    Event,
    Session,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.db.django.repositories.chronology import session_card_stats
from ludamus.links.db.django.session_visibility import is_publicly_scheduled
from ludamus.mills.enrollment_windows import EnrollmentPolicy, restricts_everyone
from ludamus.pacts.crowd import CompanionDTO, UserDTO, UserType
from ludamus.pacts.enrollment import SeatHoldRequest
from ludamus.pacts.ids import EventId, SessionId, UserId
from ludamus.pacts.legacy import (
    OCCUPYING_PARTICIPATION_STATUSES,
    EventDTO,
    RedirectError,
)
from ludamus.pacts.party import (
    PartyConsentMode,
    PartyEnrolledNotification,
    PartyMembershipStatus,
)

from .forms import AllowanceCheck, EnrollmentForm, create_enrollment_form

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest
    from ludamus.pacts.chronology import SessionCardStatsDTO
    from ludamus.pacts.party import EnrollmentPartiesDTO, SelectedEnrollmentPartyDTO

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.db.models.query import QuerySet


@dataclass
class EnrollmentRequest:
    user: UserDTO
    choice: EnrollmentChoice
    name: str = _("yourself")
    # A real co-member of the selected party (not the viewer, not a
    # companion): they are notified about seats taken on their behalf.
    is_party_member: bool = False
    # ACCEPT_INVITES member: "enroll" holds an OFFERED seat they must claim.
    needs_accept: bool = False


@dataclass
class Enrollments:
    cancelled_users: list[str]
    skipped_users: list[str]
    users_by_status: dict[SessionParticipationStatus, list[str]]

    def __init__(self) -> None:
        self.cancelled_users = []
        self.skipped_users = []
        self.users_by_status = defaultdict(list)
        # Set when a cancellation frees a held (confirmed) seat, so the caller
        # can run waiting-list promotion after the transaction commits.
        self.freed_seat = False
        # (user_id, name) of fresh enrol/waitlist sign-ups, so the caller can
        # warn the presenter about shadowbanned players after commit.
        self.signed_up_users: list[tuple[UserId, str]] = []
        # Seats taken for real party members, announced to them after commit.
        self.party_notices = PartyNotices()
        # Final +N guest headcount after this submit; None when untouched.
        self.guest_total: int | None = None
        super().__init__()


@dataclass
class PartyNotices:
    # ACCEPT_INVITES members to hold seats for (created via the promotion
    # service at the end of the batch).
    held_seats: list[UserDTO] = field(default_factory=list)
    # Real members seated directly (ACCEPT_BY_DEFAULT).
    enrolled_members: list[UserDTO] = field(default_factory=list)


def _guest_participations(
    session: Session, viewer_pk: int
) -> QuerySet[SessionParticipation]:
    # select_related("user"): guest removal deletes each row's throwaway user,
    # which would otherwise lazy-load one user per removed guest.
    return (
        SessionParticipation.objects.filter(
            session=session,
            enrolled_by_id=viewer_pk,
            user__user_type=UserType.ANONYMOUS,
        )
        .select_related("user")
        .order_by("pk")
    )


def _event_allows_anonymous_enrollment(event: Event, session: Session) -> bool:
    return any(
        config.allow_anonymous_enrollment and config.is_session_eligible(session)
        for config in event.get_active_enrollment_configs()
    )


def _get_session_or_redirect(
    request: AuthenticatedRootRequest, event_slug: str, session_id: int
) -> Session:
    try:
        session = Session.objects.get(
            event__slug=event_slug,
            event__sphere_id=request.context.current_sphere_id,
            id=session_id,
        )
    except Session.DoesNotExist:
        raise RedirectError(
            reverse("web:index"), error=_("Session not found.")
        ) from None
    viewer_id = request.context.current_user_id
    has_agenda_item = AgendaItem.objects.filter(session_id=session.pk).exists()
    has_participation = session.session_participations.filter(
        user_id=viewer_id
    ).exists()
    if has_agenda_item:
        if not is_publicly_scheduled(event_id=session.event_id, session_id=session.pk):
            raise RedirectError(
                reverse("web:index"), error=_("Session not found.")
            ) from None
    elif not has_participation:
        raise RedirectError(
            reverse("web:index"),
            error=_("No enrollment configuration is available for this session."),
        )
    # Hard event ban: a banned user cannot enrol; bounce them back to the
    # (fake-full) event page without revealing the ban.
    event = session.event
    if request.services.event_bans.is_banned(
        event_id=EventId(event.pk), user_id=viewer_id
    ):
        raise RedirectError(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        ) from None
    return session


_status_by_choice = {
    EnrollmentChoice.ENROLL: SessionParticipationStatus.CONFIRMED,
    EnrollmentChoice.WAITLIST: SessionParticipationStatus.WAITING,
}


class SessionEnrollPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest
    _policies: dict[int, EnrollmentPolicy] | None = None

    def get(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session = _get_session_or_redirect(request, event_slug, session_id)
        selection = self._party_selection(session, request.GET.get("party"))
        members = self._party_members(session, selection.selected)
        form = create_enrollment_form(
            session=session,
            current_user=request.services.enrollment.read_viewer(
                request.context.current_user_slug
            ),
            roster=EnrollmentRoster(
                companions=tuple(selection.companions),
                members=tuple(members),
                guest_count=self._guest_count(session),
            ),
            enrollment=request.services.enrollment,
        )()

        return TemplateResponse(
            request,
            "chronology/enroll_select.html",
            self._page_context(
                session=session, selection=selection, form=form, members=members
            ),
        )

    def _party_selection(
        self, session: Session, requested: str | None
    ) -> EnrollmentPartiesDTO:
        selection = self.request.services.parties.enrollment_selection(
            viewer_pk=self.request.context.current_user_id, requested_party=requested
        )
        if selection.requested_invalid:
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.pk},
                ),
                error=_("Choose one of your parties or enroll by yourself."),
            )
        return selection

    def _page_context(
        self,
        *,
        session: Session,
        selection: EnrollmentPartiesDTO,
        form: forms.Form,
        members: list[RosterMember],
    ) -> dict[str, Any]:
        return {
            "session": session,
            "seats": self._seats(session),
            "event": session.event,
            "party_choices": selection.choices,
            "selected_party": selection.selected,
            "companions": selection.companions,
            "user_data": self._get_user_participation_data(
                session=session, companions=selection.companions, members=members
            ),
            # Frontload the decision: warn the viewer up top if players they
            # shadowbanned are already signed up to this session.
            "shadowban_warnings": self.request.services.shadowban.list_session_warnings(
                viewer_id=self.request.context.current_user_id,
                session_id=SessionId(session.pk),
            ),
            "form": form,
        }

    def _seats(self, session: Session) -> SessionCardStatsDTO:
        # A viewer the presenter shadowbanned sees the session full, and is
        # never told why.
        seats = session_card_stats(session)
        banning = self.request.services.shadowban.banning_owner_ids(
            self.request.context.current_user_id
        )
        return fake_full_seats(seats) if session.presenter_id in banning else seats

    def _guest_count(self, session: Session) -> int | None:
        # None when the organizer has not opened anonymous enrollment for this
        # session — the stepper then never renders.
        if not _event_allows_anonymous_enrollment(session.event, session):
            return None
        return _guest_participations(
            session, self.request.context.current_user_id
        ).count()

    def _party_members(
        self, session: Session, selected: SelectedEnrollmentPartyDTO | None
    ) -> list[RosterMember]:
        # Real ACTIVE co-members of the viewer's selected led party. Whether a
        # member can be seated directly follows their consent (O-9): only
        # ACCEPT_INVITES members require the held-seat accept round-trip.
        if selected is None or not selected.is_own_led:
            return []
        eligible = [
            member
            for member in selected.members
            if not member.is_leader
            and not member.is_login_less
            and member.status == PartyMembershipStatus.ACTIVE
        ]
        if not eligible:
            return []
        users = {
            user.pk: user
            for user in self.request.services.enrollment.read_users(
                [member.user_pk for member in eligible]
            )
        }
        restricted = self._restricts_unconfigured(session)
        return [
            RosterMember(
                user=users[member.user_pk],
                needs_accept=member.consent_mode == PartyConsentMode.ACCEPT_INVITES,
                can_enroll=(
                    not restricted
                    or self._member_has_access(session, users[member.user_pk])
                ),
            )
            for member in eligible
            if member.user_pk in users
        ]

    def _member_has_access(self, session: Session, user: UserDTO) -> bool:
        return self.request.services.enrollment.has_slot_access(
            event=EventDTO.model_validate(session.event), user_email=user.email
        )

    @staticmethod
    def _validate_request(
        session: Session, enrollment_requests: list[EnrollmentRequest] | None = None
    ) -> None:
        if enrollment_requests and all(
            req.choice == EnrollmentChoice.CANCEL for req in enrollment_requests
        ):
            # Cancels release seats and must work with all configs deleted.
            return

        if not session.event.get_eligible_enrollment_configs(session):
            raise RedirectError(
                reverse("web:chronology:event", kwargs={"slug": session.event.slug}),
                error=_("No enrollment configuration is available for this session."),
            )

    def _get_user_participation_data(
        self,
        *,
        session: Session,
        companions: list[CompanionDTO],
        members: list[RosterMember],
    ) -> list[SessionUserParticipationData]:
        user_data: list[SessionUserParticipationData] = []

        all_users = [
            self.request.services.enrollment.read_viewer(
                self.request.context.current_user_slug
            ),
            *companions,
            *(member.user for member in members),
        ]
        flags_by_pk = {
            member.user.pk: PartyMemberFlags(
                is_member=True,
                needs_accept=member.needs_accept,
                blocked=not member.can_enroll,
            )
            for member in members
        }

        # Bulk fetch all participations for the event and users
        user_participations = SessionParticipation.objects.filter(
            user_id__in=[u.pk for u in all_users], session__event=session.event
        ).select_related("session__agenda_item")

        # Group participations by user for efficient lookup
        participations_by_user: dict[int, list[SessionParticipation]] = defaultdict(
            list
        )
        for participation in user_participations:
            user_id = participation.user_id
            participations_by_user[user_id].append(participation)

        # Add enrollment status and time conflict info for each user
        for user in all_users:
            user_parts = participations_by_user.get(user.pk, [])
            membership = flags_by_pk.get(user.pk, PartyMemberFlags())
            offered = any(
                p.status == SessionParticipationStatus.OFFERED and p.session == session
                for p in user_parts
            )

            data = SessionUserParticipationData(
                user=user,
                user_enrolled=any(
                    p.status == SessionParticipationStatus.CONFIRMED
                    and p.session == session
                    for p in user_parts
                ),
                user_waiting=any(
                    p.status == SessionParticipationStatus.WAITING
                    and p.session == session
                    for p in user_parts
                ),
                # An OFFERED row on a needs-accept member of the viewer's own
                # party is a seat held for them; any other OFFERED row keeps
                # the generic pending-offer treatment.
                seat_held=offered and membership.needs_accept,
                offer_pending=offered and not membership.needs_accept,
                membership=membership,
                has_time_conflict=any(
                    session.agenda_item.overlaps_with(p.session.agenda_item)
                    for p in user_parts
                    if p.session != session
                ),
            )
            user_data.append(data)

        return user_data

    def _render_enroll_actions(
        self, session: Session, *, enroll_error: str = "", notice: str = ""
    ) -> HttpResponse:
        # The modal-footer fragment, swapped in place after an inline
        # (HX-Request) self-enroll; state is re-read fresh from the DB. Same
        # decision as the modal's GET, but over the viewer alone — the modal
        # counts a companion's seat as theirs, and this control can only post
        # the viewer's. Such a seat is released on the group page.
        viewer_pk = self.request.context.current_user_id
        statuses = set(
            SessionParticipation.objects.filter(
                session=session, user_id=viewer_pk
            ).values_list("status", flat=True)
        )
        # Viewer-aware, like the modal's GET: a window restricted to pass
        # holders is shut for everyone else, and the swapped-in control has to
        # agree with the form that would reject them.
        access = self.request.services.enrollment.access(
            event=EventDTO.model_validate(session.event),
            viewer_slug=self.request.context.current_user_slug,
        )
        seats = self._seats(session)
        footer = build_enroll_footer(
            opens_at=access.opens_at,
            is_scheduled=True,
            participants_limit=seats.participants_limit,
            is_enrollment_available=access.seats(seats.enrollment_window_ids),
            is_ended=session.agenda_item.end_time <= datetime.now(tz=UTC),
            is_full=seats.is_full,
            user_enrolled=SessionParticipationStatus.CONFIRMED in statuses,
            user_waiting=SessionParticipationStatus.WAITING in statuses,
        )
        return TemplateResponse(
            self.request,
            "chronology/parts/session-enroll-actions.html",
            {
                "event_slug": session.event.slug,
                "session_pk": session.pk,
                "viewer_pk": viewer_pk,
                "actions": footer.actions,
                "enroll_opens_at": footer.opens_at,
                "enroll_error": enroll_error,
                # Giving up the last thing you held on a shut window leaves
                # nothing to render, so the flash is the only confirmation
                # there is. Otherwise the swapped-in badge says it better.
                "notice": notice if footer.actions is None else "",
            },
        )

    def _drain_messages(self) -> str:
        # HX-Request responses swap only the footer fragment, so nothing renders
        # the message framework — surface the flashed text inline instead.
        return " ".join(str(message) for message in messages.get_messages(self.request))

    def _add_invalid_form_messages(self, session: Session, form: forms.Form) -> None:
        # Detailed field errors without the field-name prefix.
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(self.request, str(error))

        if not self._restricts_unconfigured(session):
            messages.warning(
                self.request, _("Please review the enrollment options below.")
            )
            return

        viewer_email = self.request.services.enrollment.read_viewer(
            self.request.context.current_user_slug
        ).email
        if not viewer_email:
            messages.error(
                self.request,
                _("Email address is required for enrollment in this session."),
            )
        elif not self.request.services.enrollment.virtual_config(
            event=EventDTO.model_validate(session.event), user_email=viewer_email
        ):
            messages.error(
                self.request,
                _(
                    "Enrollment access permission is required for this session. "
                    "Please contact the organizers to obtain access."
                ),
            )
        else:
            messages.warning(
                self.request, _("Please review the enrollment options below.")
            )

    def post(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session = _get_session_or_redirect(request, event_slug, session_id)
        is_htmx = bool(request.headers.get("HX-Request"))
        selection = self._party_selection(session, request.POST.get("party"))
        members = self._party_members(session, selection.selected)
        roster = EnrollmentRoster(
            companions=tuple(selection.companions),
            members=tuple(members),
            guest_count=self._guest_count(session),
        )

        # Initialize form with POST data
        form_class = create_enrollment_form(
            session=session,
            current_user=request.services.enrollment.read_viewer(
                request.context.current_user_slug
            ),
            roster=roster,
            enrollment=request.services.enrollment,
        )
        form = form_class(data=request.POST)
        if not form.is_valid():
            self._add_invalid_form_messages(session, form)
            if is_htmx:
                return self._render_enroll_actions(
                    session, enroll_error=self._drain_messages()
                )
            return TemplateResponse(
                request,
                "chronology/enroll_select.html",
                self._page_context(
                    session=session, selection=selection, form=form, members=members
                ),
            )

        # Only validate enrollment requirements when form is valid
        enrollment_requests = self._get_enrollment_requests(form, roster, session)
        try:
            self._validate_request(session, enrollment_requests)
            self._manage_enrollments(
                form=form,
                session=session,
                roster=roster,
                party_pk=selection.selected.pk if selection.selected else None,
            )
        except RedirectError as exc:
            # An inline action races a full session (or hits a config gap): swap
            # the footer back with the reason instead of a full-page redirect.
            if is_htmx:
                return self._render_enroll_actions(
                    session,
                    enroll_error=exc.error or exc.warning or self._drain_messages(),
                )
            raise

        if is_htmx:
            # Drained either way, so a flash never leaks onto the next full
            # page load; the fragment shows it only when it has no badge to
            # confirm with.
            return self._render_enroll_actions(session, notice=self._drain_messages())
        return redirect("web:chronology:event", slug=session.event.slug)

    def _household(self, roster: EnrollmentRoster) -> list[RosterMember]:
        return [
            *(
                RosterMember(user=user)
                for user in (
                    self.request.services.enrollment.read_viewer(
                        self.request.context.current_user_slug
                    ),
                    *roster.companions,
                )
            ),
            *roster.members,
        ]

    def _get_enrollment_requests(
        self, form: forms.Form, roster: EnrollmentRoster, session: Session
    ) -> list[EnrollmentRequest]:
        # The full page submits a single "include" checkbox per person and lets
        # the system decide seat-vs-waitlist (desired-state mode). The one-click
        # inline fragment on the event page still posts explicit enroll / waitlist
        # / cancel actions, which keep their exact legacy semantics.
        if self.request.POST.get("enroll_mode") == "desired":
            return self._desired_state_requests(form, roster, session)
        return self._explicit_requests(form, roster)

    def _explicit_requests(
        self, form: forms.Form, roster: EnrollmentRoster
    ) -> list[EnrollmentRequest]:
        enrollment_requests = []
        household = self._household(roster)
        member_pks = {member.user.pk for member in roster.members}
        for member in household:
            user = member.user
            # Skip inactive users
            if not user.is_active:
                continue
            user_field = f"user_{user.pk}"
            choice = form.cleaned_data.get(user_field)
            if choice and choice != INCLUDE_VALUE:
                enrollment_requests.append(
                    EnrollmentRequest(
                        user=user,
                        choice=EnrollmentChoice(choice),
                        name=user.full_name,
                        is_party_member=user.pk in member_pks,
                        needs_accept=member.needs_accept,
                    )
                )
        return enrollment_requests

    _CURRENTLY_IN_STATUSES = (
        SessionParticipationStatus.CONFIRMED,
        SessionParticipationStatus.WAITING,
        SessionParticipationStatus.OFFERED,
    )

    def _desired_state_requests(
        self, form: forms.Form, roster: EnrollmentRoster, session: Session
    ) -> list[EnrollmentRequest]:
        household = self._household(roster)
        member_pks = {member.user.pk for member in roster.members}
        active = [member for member in household if member.user.is_active]
        status_by_pk = {
            participation.user_id: participation.status
            for participation in SessionParticipation.objects.filter(
                session=session, user_id__in=[member.user.pk for member in active]
            )
        }

        cancels: list[EnrollmentRequest] = []
        wants_in: list[RosterMember] = []
        freed = 0
        for member in active:
            user = member.user
            choices = self._choice_values(form, user.pk)
            desired_in = form.cleaned_data.get(f"user_{user.pk}") == INCLUDE_VALUE
            status = status_by_pk.get(user.pk)
            currently_in = status in self._CURRENTLY_IN_STATUSES
            if desired_in:
                # A conflicting person cannot be brought in (they would only be
                # skipped in processing anyway); leave them untouched.
                if currently_in or Session.objects.has_conflicts(session, user):
                    continue
                if (
                    EnrollmentChoice.ENROLL in choices
                    or EnrollmentChoice.WAITLIST in choices
                ):
                    wants_in.append(member)
            elif currently_in and EnrollmentChoice.CANCEL in choices:
                cancels.append(
                    EnrollmentRequest(
                        user=user,
                        choice=EnrollmentChoice.CANCEL,
                        name=user.full_name,
                        is_party_member=user.pk in member_pks,
                        needs_accept=member.needs_accept,
                    )
                )
                if status in OCCUPYING_PARTICIPATION_STATUSES:
                    freed += 1

        return cancels + self._route_wants_in(
            form, session, wants_in, member_pks, freed
        )

    def _actor_policy(self, session: Session) -> EnrollmentPolicy:
        if self._policies is None:
            self._policies = {}
        if session.pk not in self._policies:
            viewer = self.request.services.enrollment.read_viewer(
                self.request.context.current_user_slug
            )
            self._policies[session.pk] = EnrollmentPolicy.for_actor(
                session.event.get_eligible_enrollment_configs(session),
                is_configured_user=self._member_has_access(session, viewer),
            )
        return self._policies[session.pk]

    @staticmethod
    def _restricts_unconfigured(session: Session) -> bool:
        return restricts_everyone(
            session.event.get_eligible_enrollment_configs(session)
        )

    @staticmethod
    def _spots(
        enrollment_policy: EnrollmentPolicy, session: Session, *, freed: int
    ) -> int:
        occupied = SessionParticipation.objects.filter(
            session=session, status__in=OCCUPYING_PARTICIPATION_STATUSES
        ).count()
        return enrollment_policy.available_slots(
            participants_limit=session.participants_limit,
            enrolled_count=occupied - freed,
        )

    def _available_slots(self, session: Session, *, freed: int = 0) -> int:
        return self._spots(self._actor_policy(session), session, freed=freed)

    def _route_wants_in(
        self,
        form: forms.Form,
        session: Session,
        wants_in: list[RosterMember],
        member_pks: set[UserId],
        freed: int,
    ) -> list[EnrollmentRequest]:
        # Fill confirmed seats first (viewer, then companions, then members — the
        # household order), overflow to the waiting list. Counting matches
        available = self._available_slots(session, freed=freed)
        routed: list[EnrollmentRequest] = []
        for member in wants_in:
            user = member.user
            choices = self._choice_values(form, user.pk)
            has_room = available > 0
            if member.needs_accept:
                # A held seat always occupies a confirmed spot; there is no
                # waiting-list form of it, so only offer one when there is room.
                if not has_room:
                    continue
                choice = EnrollmentChoice.ENROLL
            elif has_room and EnrollmentChoice.ENROLL in choices:
                choice = EnrollmentChoice.ENROLL
            elif EnrollmentChoice.WAITLIST in choices:
                choice = EnrollmentChoice.WAITLIST
            else:
                # Full and this person cannot wait (limit reached / no access).
                continue
            if choice == EnrollmentChoice.ENROLL:
                available -= 1
            routed.append(
                EnrollmentRequest(
                    user=user,
                    choice=choice,
                    name=user.full_name,
                    is_party_member=user.pk in member_pks,
                    needs_accept=member.needs_accept,
                )
            )
        return routed

    @staticmethod
    def _choice_values(form: forms.Form, user_pk: int) -> set[EnrollmentChoice]:
        form_field = form.fields.get(f"user_{user_pk}")
        if not isinstance(form_field, forms.ChoiceField):
            return set()
        return {choice for choice in EnrollmentChoice if form_field.valid_value(choice)}

    def _process_enrollments(
        self,
        *,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        party_pk: int | None,
        guests_target: int | None = None,
        allowance: AllowanceCheck | None = None,
    ) -> Enrollments:
        enrollments = Enrollments()

        # SAFETY: the lock order of every seat decision (architecture.md):
        # this Session row, then lock_seat_holders, then the checks.
        session = Session.objects.select_for_update().get(id=session.id)
        # The guest delta is derived from the absolute target under the session
        # lock, so a replayed submit (double-click, refresh) is a no-op instead
        # of duplicating guests.
        guests_delta = 0
        if guests_target is not None:
            guests_delta = (
                guests_target
                - _guest_participations(
                    session, self.request.context.current_user_id
                ).count()
            )
        guest_seats_needed = max(guests_delta, 0)
        guest_seats_freed = max(-guests_delta, 0)
        self._lock_seat_holders(
            session_id=session.id,
            enrollment_requests=enrollment_requests,
            frees_seats=bool(guest_seats_freed)
            or any(
                req.choice == EnrollmentChoice.CANCEL for req in enrollment_requests
            ),
        )
        # The form asked first, before any lock; this answer is the one that
        # counts, read after every other request on these passes committed.
        if allowance is not None and not allowance.passes(
            self.request.services.enrollment
        ):
            logger.info(
                "Enroll into session %s refused under the lock: passes spent",
                session.id,
            )
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.id},
                ),
                error=allowance.refusal(self.request.services.enrollment),
            )
        if self._is_capacity_invalid(
            enrollment_requests,
            session,
            guest_seats_needed=guest_seats_needed,
            guest_seats_freed=guest_seats_freed,
        ):
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.id},
                )
            )

        participations = SessionParticipation.objects.filter(session=session).order_by(
            "creation_time"
        )

        # Players the presenter shadowbanned must not be seated — even when an
        # unbanned manager tries to enroll a banned companion.
        shadowbanned_ids = (
            self.request.services.shadowban.banned_user_ids(
                UserId(session.presenter_id)
            )
            if session.presenter_id
            else set()
        )

        # Cancellations first: a seat freed in this batch must be available to a
        # companion enrolling in the same submit (e.g. swapping a seat on a
        # full session).
        ordered_requests = sorted(
            enrollment_requests,
            key=lambda req: 0 if req.choice == EnrollmentChoice.CANCEL else 1,
        )

        for req in ordered_requests:
            if req.choice == EnrollmentChoice.CANCEL:
                self._handle_cancellation(req, participations, enrollments)
            else:
                self._check_and_create_enrollment(
                    req=req,
                    session=session,
                    enrollments=enrollments,
                    shadowbanned_ids=shadowbanned_ids,
                    party_pk=party_pk,
                )
        if guest_seats_needed or guest_seats_freed:
            self._adjust_guests(
                session=session,
                add=guest_seats_needed,
                remove=guest_seats_freed,
                party_pk=party_pk,
                enrollments=enrollments,
            )

        self._hold_member_seats(session, enrollments, party_pk)
        return enrollments

    def _lock_seat_holders(
        self,
        *,
        session_id: int,
        enrollment_requests: list[EnrollmentRequest],
        frees_seats: bool,
    ) -> None:
        # The viewer always: they host the guests and own the passes the batch
        # spends. A batch that frees a seat refills it in this request's
        # transaction, so it takes the waiters now as well. Called on the
        # repository directly, beside the Session lock it pairs with.
        SeatHolderLocks.lock_seat_holders(
            user_ids=[
                self.request.context.current_user_id,
                *(req.user.pk for req in enrollment_requests),
            ],
            waiters_of=session_id if frees_seats else None,
        )

    @staticmethod
    def _handle_cancellation(
        req: EnrollmentRequest,
        participations: Iterable[SessionParticipation],
        enrollments: Enrollments,
    ) -> None:
        # A racing request may have already deleted the row (the form would
        # otherwise reject "cancel"); skip gracefully instead of raising.
        existing_participation = next(
            (p for p in participations if p.user.id == req.user.pk), None
        )
        if existing_participation is None:
            enrollments.skipped_users.append(
                _("%(name)s (no enrollment to cancel)") % {"name": req.name}
            )
            return

        # A freed confirmed (or held offered) seat triggers waiting-list
        # promotion after the transaction commits, via the service.
        if existing_participation.status in OCCUPYING_PARTICIPATION_STATUSES:
            enrollments.freed_seat = True
        existing_participation.delete()
        enrollments.cancelled_users.append(req.name)

    @staticmethod
    def _check_and_create_enrollment(
        *,
        req: EnrollmentRequest,
        session: Session,
        enrollments: Enrollments,
        shadowbanned_ids: set[UserId],
        party_pk: int | None,
    ) -> None:
        # Check if user is the session presenter
        if session.presenter_id and req.user.pk == session.presenter_id:
            enrollments.skipped_users.append(
                _("%(name)s (session host)") % {"name": req.name}
            )
            return

        # Shadowban: skip without revealing the ban (neutral reason).
        if req.user.pk in shadowbanned_ids:
            enrollments.skipped_users.append(
                _("%(name)s (not available)") % {"name": req.name}
            )
            return

        # Check for time conflicts for confirmed enrollment
        if req.choice == EnrollmentChoice.ENROLL and Session.objects.has_conflicts(
            session, req.user
        ):
            enrollments.skipped_users.append(
                _("%(name)s (time conflict)") % {"name": req.name}
            )
            return

        # Use get_or_create to prevent duplicate enrollments in race conditions
        participation = SessionParticipation.objects.filter(
            session=session, user_id=req.user.pk
        ).first()
        is_fresh_signup = participation is None

        if req.needs_accept:
            # An ACCEPT_INVITES member is never seated directly: their seat is
            # held by the promotion service at the end of this batch, still
            # inside its transaction (see _hold_member_seats).
            if participation is not None:
                enrollments.skipped_users.append(
                    _("%(name)s (manages their own enrollment)") % {"name": req.name}
                )
                return
            enrollments.party_notices.held_seats.append(req.user)
            enrollments.signed_up_users.append((UserId(req.user.pk), req.name))
            return

        if not participation:
            participation = SessionParticipation(session=session, user_id=req.user.pk)

        participation.status = _status_by_choice[req.choice]
        # The latest submit's grouping intent wins: this seat promotes with the
        # party it was (re-)enrolled through.
        participation.party_id = party_pk
        participation.save()

        if req.is_party_member and is_fresh_signup:
            enrollments.party_notices.enrolled_members.append(req.user)

        enrollments.users_by_status[_status_by_choice[req.choice]].append(req.name)
        # Only a brand-new participation is a "signup" worth warning a banner
        # about — re-confirming or status changes must not re-alert.
        if is_fresh_signup:
            enrollments.signed_up_users.append((UserId(req.user.pk), req.name))

    def _hold_member_seats(
        self, session: Session, enrollments: Enrollments, party_pk: int | None
    ) -> None:
        # The promotion service owns the hold (OFFERED row + claim token +
        # expiry timer + notification); the batch transaction wraps it so the
        # seats stay consistent with the capacity check above.
        if not enrollments.party_notices.held_seats:
            return
        actor_name = self._actor_name()
        for member in enrollments.party_notices.held_seats:
            self.request.services.waitlist_promotion.hold_seat(
                hold=SeatHoldRequest(
                    session_id=session.pk,
                    session_title=session.title,
                    user_id=member.pk,
                    party_id=party_pk,
                    actor_name=actor_name,
                )
            )

    def _actor_name(self) -> str:
        return self.request.services.enrollment.read_viewer(
            self.request.context.current_user_slug
        ).full_name

    def _notify_party_members(self, session: Session, enrollments: Enrollments) -> None:
        if not enrollments.party_notices.enrolled_members:
            return
        actor_name = self._actor_name()
        for member in enrollments.party_notices.enrolled_members:
            self.request.services.parties.announce_member_enrolled(
                PartyEnrolledNotification(
                    recipient_user_id=member.pk,
                    actor_name=actor_name,
                    session_id=session.pk,
                    session_title=session.title,
                    event_slug=session.event.slug,
                )
            )

    def _send_message(self, enrollments: Enrollments) -> None:
        for users, message, level in (
            (
                enrollments.users_by_status[SessionParticipationStatus.CONFIRMED],
                _("Enrolled: {}"),
                messages.SUCCESS,
            ),
            (
                enrollments.users_by_status[SessionParticipationStatus.WAITING],
                _("Added to waiting list: {}"),
                messages.SUCCESS,
            ),
            (
                [held.full_name for held in enrollments.party_notices.held_seats],
                _("Seat held (awaiting their approval): {}"),
                messages.SUCCESS,
            ),
            (enrollments.cancelled_users, _("Cancelled: {}"), messages.SUCCESS),
            (
                enrollments.skipped_users,
                _("Skipped (already enrolled or conflicts): {}"),
                messages.WARNING,
            ),
        ):
            if users:
                messages.add_message(
                    self.request, level, message.format(", ".join(users))
                )
        if enrollments.guest_total is not None:
            messages.success(
                self.request, _("Guests you bring: {}").format(enrollments.guest_total)
            )

    def _is_capacity_invalid(
        self,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        *,
        guest_seats_needed: int = 0,
        guest_seats_freed: int = 0,
    ) -> bool:
        member_count = sum(
            1 for req in enrollment_requests if req.choice == EnrollmentChoice.ENROLL
        )
        if (enroll_count := member_count + guest_seats_needed) == 0:
            return False

        # A cancellation in the same batch frees its held seat (CONFIRMED or
        # OFFERED both occupy capacity) — credit it back before checking.
        cancelling_user_ids = {
            req.user.pk
            for req in enrollment_requests
            if req.choice == EnrollmentChoice.CANCEL
        }
        freed_spots = guest_seats_freed
        if cancelling_user_ids:
            freed_spots += SessionParticipation.objects.filter(
                session=session,
                user_id__in=cancelling_user_ids,
                status__in=OCCUPYING_PARTICIPATION_STATUSES,
            ).count()

        session_policy = EnrollmentPolicy.for_actor(
            session.event.get_eligible_enrollment_configs(session),
            is_configured_user=True,
        )
        available_spots = (
            self._spots(session_policy, session, freed=freed_spots)
            if session_policy.can_enroll
            else freed_spots
        )
        member_spots = self._available_slots(session, freed=freed_spots)
        if member_count > member_spots:
            self._report_overflow(member_count, member_spots, blame_guests=False)
            return True
        if enroll_count > available_spots:
            self._report_overflow(enroll_count, available_spots, blame_guests=True)
            return True
        return False

    def _report_overflow(
        self, requested: int, available: int, *, blame_guests: bool
    ) -> None:
        message = (
            _(
                "Not enough spots available. {} spots requested, {} available. "
                "Bring fewer guests or use the waiting list for account "
                "holders."
            )
            if blame_guests
            else _(
                "Not enough spots available. {} spots requested, {} available. "
                "Please use waiting list for some users."
            )
        )
        messages.error(self.request, str(message).format(requested, available))

    def _manage_enrollments(
        self,
        *,
        form: EnrollmentForm,
        session: Session,
        roster: EnrollmentRoster,
        party_pk: int | None,
    ) -> None:
        enrollment_requests = self._get_enrollment_requests(form, roster, session)
        # An empty guests box means "leave unchanged" (the field is prefilled
        # with the current count, so this only happens when cleared on purpose).
        guests_target: int | None = (
            form.cleaned_data.get("guests") if roster.guest_count is not None else None
        )
        guests_changed = (
            guests_target is not None and guests_target != roster.guest_count
        )
        if enrollment_requests or guests_changed:
            with transaction.atomic():
                enrollments = self._process_enrollments(
                    enrollment_requests=enrollment_requests,
                    session=session,
                    party_pk=party_pk,
                    guests_target=guests_target,
                    allowance=form.allowance_check,
                )

            # T1: a freed seat promotes/offers the next waiter (who is notified
            # directly), instead of the canceller stealing the message.
            if enrollments.freed_seat:
                self.request.services.waitlist_promotion.fill_freed_seats(
                    session_id=session.id
                )

            # Warn the presenter (by email) if a shadowbanned player signed up.
            self.request.services.shadowban.notify_signups(
                session_id=SessionId(session.id), signed_up=enrollments.signed_up_users
            )

            self._notify_party_members(session, enrollments)

            # Send message outside transaction
            self._send_message(enrollments)
        else:
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.id},
                ),
                warning=(
                    # On the desired-state page every submit is a valid statement
                    # of who should be in — an unchanged one is simply a no-op,
                    # not a selection mistake. Same for a submit whose only
                    # touched control is the (unchanged) guests field.
                    _("No changes.")
                    if guests_target is not None
                    or self.request.POST.get("enroll_mode") == "desired"
                    else _("Please select at least one user to enroll.")
                ),
            )

    def _adjust_guests(
        self,
        *,
        session: Session,
        add: int,
        remove: int,
        party_pk: int | None,
        enrollments: Enrollments,
    ) -> None:
        # Runs inside the enrollment transaction, after the per-user requests,
        # with the session row locked.
        viewer_pk = self.request.context.current_user_id
        if add:
            self._create_guests(session=session, count=add, party_pk=party_pk)
        if remove:
            # Trim the most recent guests; their throwaway rows go with them.
            doomed = list(_guest_participations(session, viewer_pk))[-remove:]
            for participation in doomed:
                participation.user.delete()
            enrollments.freed_seat = True
        enrollments.guest_total = _guest_participations(session, viewer_pk).count()

    def _create_guests(
        self, *, session: Session, count: int, party_pk: int | None
    ) -> None:
        self.request.services.enrollment.create_guests(
            session_id=session.pk,
            count=count,
            party_id=party_pk,
            enrolled_by_id=self.request.context.current_user_id,
            viewer_name=self._actor_name(),
        )
