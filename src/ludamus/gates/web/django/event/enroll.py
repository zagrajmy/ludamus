"""The enroll page: who of the viewer's household is in a session.

Parses the form and words the outcome; `services.member_enrollment` decides
every seat. The full page posts one "include" box per person; the one-click
fragment on the event page posts explicit actions and gets its footer back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.enroll_forms import (
    allowance_message,
    build_enroll_form,
)
from ludamus.gates.web.django.event.enroll_presentation import build_enroll_footer
from ludamus.gates.web.django.event.event_presentation import fake_full_seats
from ludamus.gates.web.django.redirects import RedirectError
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.enrollment_member import (
    AccessProblem,
    AllowanceSpentError,
    MemberEnrollError,
    MemberEnrollErrorCode,
    MemberEnrollQuery,
    MemberEnrollSubmission,
    NothingToChangeError,
    SeatsShortError,
    SkipReason,
)
from ludamus.pacts.ids import SessionId, UserId

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest
    from ludamus.gates.web.django.event.enroll_forms import EnrollmentForm
    from ludamus.pacts.chronology import SessionCardStatsDTO
    from ludamus.pacts.enrollment_member import MemberEnrollOutcome, MemberEnrollPageDTO


def _skipped_text(reason: SkipReason, name: str) -> str:
    match reason:
        case SkipReason.NO_ENROLLMENT_TO_CANCEL:
            text = _("%(name)s (no enrollment to cancel)")
        case SkipReason.SESSION_HOST:
            text = _("%(name)s (session host)")
        case SkipReason.NOT_AVAILABLE:
            text = _("%(name)s (not available)")
        case SkipReason.TIME_CONFLICT:
            text = _("%(name)s (time conflict)")
        case SkipReason.MANAGES_OWN:
            text = _("%(name)s (manages their own enrollment)")
    return text % {"name": name}


class SessionEnrollPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        page = self._read_page(event_slug, session_id, request.GET.get("party"))
        return self._render_page(page, build_enroll_form(page)())

    def post(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        page = self._read_page(event_slug, session_id, request.POST.get("party"))
        is_htmx = bool(request.headers.get("HX-Request"))
        form = build_enroll_form(page)(data=request.POST)
        form.is_valid()
        # The passes are asked about before any lock, so a refusal reads as
        # the form's own; the service asks again under the locks.
        if refusal := request.services.member_enrollment.allowance_refusal(
            page=page, choices=form.person_choices()
        ):
            form.add_error(f"user_{refusal.user_id}", allowance_message(refusal))
        if not form.is_valid():
            self._add_invalid_form_messages(page, form)
            if is_htmx:
                return self._render_footer(page, enroll_error=self._drain_messages())
            return self._render_page(page, form)

        try:
            outcome = self._submit(page, form)
        except RedirectError as exc:
            # An inline action racing a full session (or a window gap) swaps
            # the footer back with the reason instead of a full-page redirect.
            if is_htmx:
                return self._render_footer(
                    page,
                    enroll_error=exc.error or exc.warning or self._drain_messages(),
                )
            raise
        self._send_messages(outcome)
        if is_htmx:
            # Drained either way, so a flash never leaks onto the next full
            # page; the fragment shows it only when it has no badge to
            # confirm with.
            return self._render_footer(page, notice=self._drain_messages())
        return redirect("web:chronology:event", slug=page.session.event.slug)

    def _read_page(
        self, event_slug: str, session_id: int, requested_party: str | None
    ) -> MemberEnrollPageDTO:
        context = self.request.context
        try:
            return self.request.services.member_enrollment.read_page(
                MemberEnrollQuery(
                    event_slug=event_slug,
                    session_id=session_id,
                    sphere_id=context.current_sphere_id,
                    viewer_id=context.current_user_id,
                    viewer_slug=context.current_user_slug,
                    requested_party=requested_party,
                )
            )
        except MemberEnrollError as exc:
            raise self._redirect(exc.code, event_slug, session_id) from None

    @staticmethod
    def _redirect(
        code: MemberEnrollErrorCode, event_slug: str, session_id: int
    ) -> RedirectError:
        match code:
            case MemberEnrollErrorCode.SESSION_NOT_FOUND:
                return RedirectError(
                    reverse("web:index"), error=_("Session not found.")
                )
            case MemberEnrollErrorCode.NO_ENROLLMENT_CONFIG:
                return RedirectError(
                    reverse("web:index"),
                    error=_(
                        "No enrollment configuration is available for this session."
                    ),
                )
            case MemberEnrollErrorCode.BANNED:
                return RedirectError(
                    reverse("web:chronology:event", kwargs={"slug": event_slug})
                )
            case MemberEnrollErrorCode.INVALID_PARTY:
                return RedirectError(
                    _enroll_url(event_slug, session_id),
                    error=_("Choose one of your parties or enroll by yourself."),
                )
            case MemberEnrollErrorCode.NO_ELIGIBLE_WINDOW:
                return RedirectError(
                    reverse("web:chronology:event", kwargs={"slug": event_slug}),
                    error=_(
                        "No enrollment configuration is available for this session."
                    ),
                )

    def _submit(
        self, page: MemberEnrollPageDTO, form: EnrollmentForm
    ) -> MemberEnrollOutcome:
        session = page.session
        here = _enroll_url(session.event.slug, session.pk)
        try:
            return self.request.services.member_enrollment.submit(
                page=page,
                submission=MemberEnrollSubmission(
                    choices=form.person_choices(),
                    guests=form.cleaned_data.get("guests"),
                    desired=self.request.POST.get("enroll_mode") == "desired",
                ),
            )
        except MemberEnrollError as exc:
            raise self._redirect(exc.code, session.event.slug, session.pk) from None
        except AllowanceSpentError as exc:
            raise RedirectError(here, error=allowance_message(exc.refusal)) from None
        except SeatsShortError as exc:
            self._report_overflow(exc)
            raise RedirectError(here) from None
        except NothingToChangeError as exc:
            # A desired-state submit always states who should be in, so an
            # unchanged one is a no-op, not a selection mistake.
            raise RedirectError(
                here,
                warning=(
                    _("No changes.")
                    if exc.quiet
                    else _("Please select at least one user to enroll.")
                ),
            ) from None

    def _report_overflow(self, exc: SeatsShortError) -> None:
        message = (
            _(
                "Not enough spots available. {} spots requested, {} available. "
                "Bring fewer guests or use the waiting list for account "
                "holders."
            )
            if exc.blame_guests
            else _(
                "Not enough spots available. {} spots requested, {} available. "
                "Please use waiting list for some users."
            )
        )
        messages.error(self.request, message.format(exc.requested, exc.available))

    def _send_messages(self, outcome: MemberEnrollOutcome) -> None:
        for names, message, level in (
            (outcome.enrolled, _("Enrolled: {}"), messages.SUCCESS),
            (outcome.waitlisted, _("Added to waiting list: {}"), messages.SUCCESS),
            (
                outcome.held,
                _("Seat held (awaiting their approval): {}"),
                messages.SUCCESS,
            ),
            (outcome.cancelled, _("Cancelled: {}"), messages.SUCCESS),
            (
                [_skipped_text(skip.reason, skip.name) for skip in outcome.skipped],
                _("Skipped (already enrolled or conflicts): {}"),
                messages.WARNING,
            ),
        ):
            if names:
                messages.add_message(
                    self.request, level, message.format(", ".join(names))
                )
        if outcome.guest_total is not None:
            messages.success(
                self.request, _("Guests you bring: {}").format(outcome.guest_total)
            )

    def _add_invalid_form_messages(
        self, page: MemberEnrollPageDTO, form: EnrollmentForm
    ) -> None:
        # Detailed field errors without the field-name prefix.
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(self.request, str(error))
        match page.access_problem:
            case AccessProblem.EMAIL:
                messages.error(
                    self.request,
                    _("Email address is required for enrollment in this session."),
                )
            case AccessProblem.ACCESS:
                messages.error(
                    self.request,
                    _(
                        "Enrollment access permission is required for this session. "
                        "Please contact the organizers to obtain access."
                    ),
                )
            case None:
                messages.warning(
                    self.request, _("Please review the enrollment options below.")
                )

    def _render_page(
        self, page: MemberEnrollPageDTO, form: EnrollmentForm
    ) -> TemplateResponse:
        services = self.request.services
        session = page.session
        return TemplateResponse(
            self.request,
            "chronology/enroll_select.html",
            {
                "session": session,
                "seats": self._seats(page, session.seats),
                "event": session.event,
                "party_choices": page.parties.choices,
                "selected_party": page.parties.selected,
                "companions": page.parties.companions,
                "user_data": list(page.user_data),
                # Frontload the decision: warn the viewer up top if players
                # they shadowbanned are already signed up to this session.
                "shadowban_warnings": services.shadowban.list_session_warnings(
                    viewer_id=self.request.context.current_user_id,
                    session_id=SessionId(session.pk),
                ),
                "form": form,
            },
        )

    def _seats(
        self, page: MemberEnrollPageDTO, seats: SessionCardStatsDTO
    ) -> SessionCardStatsDTO:
        # A viewer the presenter shadowbanned sees the session full, and is
        # never told why.
        banning = self.request.services.shadowban.banning_owner_ids(
            self.request.context.current_user_id
        )
        presenter_id = page.session.presenter_id
        if presenter_id is not None and UserId(presenter_id) in banning:
            return fake_full_seats(seats)
        return seats

    def _render_footer(
        self, page: MemberEnrollPageDTO, *, enroll_error: str = "", notice: str = ""
    ) -> HttpResponse:
        # The modal-footer fragment, swapped in place after an inline
        # self-enroll; state is re-read fresh. Same decision as the modal's
        # GET, but over the viewer alone: the modal counts a companion's seat
        # as theirs, and this control can only post the viewer's.
        session = page.session
        viewer_pk = self.request.context.current_user_id
        footer_state = self.request.services.member_enrollment.read_footer(
            session_id=session.pk, viewer_id=viewer_pk
        )
        # Viewer-aware, like the modal's GET: a window restricted to pass
        # holders is shut for everyone else, and the swapped-in control has
        # to agree with the form that would reject them.
        access = self.request.services.enrollment.access(
            event=session.event, viewer_slug=self.request.context.current_user_slug
        )
        seats = self._seats(page, footer_state.seats)
        footer = build_enroll_footer(
            opens_at=access.opens_at,
            is_scheduled=True,
            participants_limit=seats.participants_limit,
            is_enrollment_available=access.seats(seats.enrollment_window_ids),
            is_ended=(
                session.agenda_item is not None
                and session.agenda_item.end_time <= datetime.now(tz=UTC)
            ),
            is_full=seats.is_full,
            user_enrolled=(
                footer_state.viewer_status == SessionParticipationStatus.CONFIRMED
            ),
            user_waiting=(
                footer_state.viewer_status == SessionParticipationStatus.WAITING
            ),
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
                # nothing to render, so the flash is the only confirmation.
                # Otherwise the swapped-in badge says it better.
                "notice": notice if footer.actions is None else "",
            },
        )

    def _drain_messages(self) -> str:
        # HX-Request responses swap only the footer fragment, so nothing
        # renders the message framework: surface the flashed text inline.
        return " ".join(str(message) for message in messages.get_messages(self.request))


def _enroll_url(event_slug: str, session_id: int) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )
