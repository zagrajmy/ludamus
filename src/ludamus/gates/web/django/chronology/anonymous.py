from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.pacts.enrollment import (
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentRequestDTO,
    AnonymousEnrollOutcome,
)

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.enrollment import AnonymousCancelResultDTO

_SESSION_KEYS = (
    "anonymous_user_code",
    "anonymous_enrollment_active",
    "anonymous_event_id",
    "anonymous_site_id",
)

_ERROR_MESSAGES: dict[AnonymousEnrollmentErrorCode, _StrPromise] = {
    AnonymousEnrollmentErrorCode.EVENT_NOT_FOUND: gettext_lazy("Event not found."),
    AnonymousEnrollmentErrorCode.NOT_AVAILABLE_FOR_EVENT: gettext_lazy(
        "Anonymous enrollment is not available for this event."
    ),
    AnonymousEnrollmentErrorCode.SESSION_NOT_FOUND: gettext_lazy("Session not found."),
    AnonymousEnrollmentErrorCode.NOT_FOR_THIS_SESSION: gettext_lazy(
        "Anonymous enrollment is not available for this session."
    ),
    AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG: gettext_lazy(
        "No enrollment configuration is available for this session."
    ),
    AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED: gettext_lazy(
        "Anonymous enrollment for this session is closed."
    ),
    AnonymousEnrollmentErrorCode.SESSION_EXPIRED: gettext_lazy(
        "Anonymous session expired."
    ),
    AnonymousEnrollmentErrorCode.USER_NOT_FOUND: gettext_lazy(
        "Anonymous user not found."
    ),
    AnonymousEnrollmentErrorCode.NAME_REQUIRED: gettext_lazy("Name is required."),
}


def _store_anonymous_state(
    request: RootRequest, *, code: str, event_id: int, site_id: int
) -> None:
    request.session["anonymous_user_code"] = code
    request.session["anonymous_enrollment_active"] = True
    request.session["anonymous_event_id"] = event_id
    request.session["anonymous_site_id"] = site_id


def _state_error_redirect(request: RootRequest) -> HttpResponse | None:
    if not request.session.get("anonymous_enrollment_active"):
        messages.error(request, _("Anonymous enrollment is not active."))
        return redirect("web:index")
    if request.session.get("anonymous_site_id") != request.context.current_site_id:
        messages.error(
            request, _("Anonymous enrollment session is not valid for this site.")
        )
        return redirect("web:index")
    return None


def _enrollment_request(
    request: RootRequest, *, event_slug: str, session_id: int
) -> AnonymousEnrollmentRequestDTO:
    return AnonymousEnrollmentRequestDTO(
        event_slug=event_slug,
        session_id=session_id,
        site_id=request.context.current_site_id,
        anonymous_event_id=request.session.get("anonymous_event_id"),
        code=request.session.get("anonymous_user_code"),
    )


def _cancel_response(
    request: RootRequest, result: AnonymousCancelResultDTO
) -> HttpResponse:
    if result.cancelled:
        messages.success(
            request,
            _("Successfully cancelled enrollment in session: %(title)s")
            % {"title": result.session_title},
        )
    else:
        messages.warning(request, _("No enrollment found to cancel."))
    return redirect("web:chronology:event", slug=result.event_slug)


def _error_response(
    request: RootRequest,
    error: AnonymousEnrollmentError,
    *,
    event_slug: str,
    session_id: int,
) -> HttpResponse:
    messages.error(request, _ERROR_MESSAGES[error.code])
    if error.code == AnonymousEnrollmentErrorCode.NAME_REQUIRED:
        return redirect(
            "web:chronology:session-enrollment-anonymous",
            event_slug=event_slug,
            session_id=session_id,
        )
    if error.event_slug:
        return redirect("web:chronology:event", slug=error.event_slug)
    return redirect("web:index")


class EventAnonymousActivateActionView(View):
    @staticmethod
    def get(request: RootRequest, event_slug: str) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:chronology:event", slug=event_slug)

        try:
            activation = request.services.anonymous_enrollment.activate(
                event_slug=event_slug
            )
        except AnonymousEnrollmentError as error:
            messages.error(request, _ERROR_MESSAGES[error.code])
            if error.event_slug:
                return redirect("web:chronology:event", slug=error.event_slug)
            return redirect("web:index")

        _store_anonymous_state(
            request,
            code=activation.code,
            event_id=activation.event_id,
            site_id=request.context.current_site_id,
        )
        return redirect("web:chronology:event", slug=activation.event_slug)


class SessionEnrollmentAnonymousPageView(View):
    @staticmethod
    def get(request: RootRequest, event_slug: str, session_id: int) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect(
                "web:chronology:session-enrollment",
                event_slug=event_slug,
                session_id=session_id,
            )
        if early_redirect := _state_error_redirect(request):
            return early_redirect

        try:
            page = request.services.anonymous_enrollment.get_enroll_page(
                _enrollment_request(
                    request, event_slug=event_slug, session_id=session_id
                )
            )
        except AnonymousEnrollmentError as error:
            return _error_response(
                request, error, event_slug=event_slug, session_id=session_id
            )

        context = {
            "session": page.session,
            "event_slug": page.session.event_slug,
            "user_name": page.user_name,
            "anonymous_code": page.anonymous_code,
            "needs_user_data": page.needs_user_data,
            "enrollment_status": page.enrollment_status,
            "is_enrolled": page.is_enrolled,
        }
        return TemplateResponse(request, "chronology/anonymous_enroll.html", context)

    @staticmethod
    def post(request: RootRequest, event_slug: str, session_id: int) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect(
                "web:chronology:session-enrollment",
                event_slug=event_slug,
                session_id=session_id,
            )
        if early_redirect := _state_error_redirect(request):
            return early_redirect

        enrollment_request = _enrollment_request(
            request, event_slug=event_slug, session_id=session_id
        )
        name = request.POST.get("name", "").strip()
        try:
            if request.POST.get("action", "enroll") == "cancel":
                return _cancel_response(
                    request,
                    request.services.anonymous_enrollment.cancel(
                        enrollment_request, name
                    ),
                )
            enrolled = request.services.anonymous_enrollment.enroll(
                enrollment_request, name
            )
        except AnonymousEnrollmentError as error:
            return _error_response(
                request, error, event_slug=event_slug, session_id=session_id
            )

        if enrolled.outcome == AnonymousEnrollOutcome.CONFLICT:
            messages.error(
                request,
                _(
                    "Cannot enroll: You are already enrolled in another session "
                    "that conflicts with this time slot."
                ),
            )
            return redirect(
                "web:chronology:session-enrollment-anonymous",
                event_slug=event_slug,
                session_id=session_id,
            )
        if enrolled.outcome == AnonymousEnrollOutcome.WAITLISTED:
            messages.success(
                request,
                _(
                    "Session is full. You have been added to the waiting list "
                    "for: %(title)s"
                )
                % {"title": enrolled.session_title},
            )
        else:
            messages.success(
                request,
                _("Successfully enrolled in session: %(title)s")
                % {"title": enrolled.session_title},
            )
        return redirect("web:chronology:event", slug=enrolled.event_slug)


class AnonymousLoadActionView(View):
    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:index")

        if not (code := request.POST.get("code", "").strip()):
            messages.error(request, _("Please enter a code."))
            return _referer_redirect(request)

        try:
            load = request.services.anonymous_enrollment.load_by_code(code=code)
        except AnonymousEnrollmentError as error:
            if error.code == AnonymousEnrollmentErrorCode.USER_NOT_FOUND:
                messages.error(request, _("Invalid code. Please check and try again."))
                return _referer_redirect(request)
            messages.warning(request, _("No enrollments found for this code."))
            return redirect("web:index")

        _store_anonymous_state(
            request, code=code, event_id=load.event_id, site_id=load.site_id
        )
        messages.success(
            request, _("Code loaded successfully. You can now manage your enrollments.")
        )
        return redirect("web:chronology:event", slug=load.event_slug)


def _referer_redirect(request: RootRequest) -> HttpResponse:
    # Try to send the visitor back to the event page they came from.
    referer = request.META.get("HTTP_REFERER", "")
    if "event" in referer:
        return redirect(referer)
    return redirect("web:index")


class AnonymousResetActionView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        event_id = request.session.get("anonymous_event_id")
        event_slug = (
            request.services.anonymous_enrollment.event_slug_by_id(event_id)
            if event_id
            else None
        )

        for key in _SESSION_KEYS:
            request.session.pop(key, None)

        if event_slug:
            # Activating anew generates a fresh code for the visitor.
            return redirect(
                "web:chronology:event-anonymous-activate", event_slug=event_slug
            )
        return redirect("web:index")
