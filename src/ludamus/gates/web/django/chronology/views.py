from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    dynamic_fields_form,
    field_descriptors,
)
from ludamus.gates.web.django.forms import SessionEditForm
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.mills.chronology import SessionEditNotAllowedError
from ludamus.pacts import (
    NotFoundError,
    RedirectError,
    SessionFieldValueData,
    SessionStatus,
)
from ludamus.pacts.chronology import ProposalAcceptDeniedError, SpaceTimeConflictError
from ludamus.pacts.durations import parse_duration
from ludamus.pacts.ids import SessionId
from ludamus.pacts.images import stored_file

from .forms import create_proposal_acceptance_form

if TYPE_CHECKING:

    from django import forms
    from django.http import QueryDict

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts import (
        AuthenticatedRequestContext,
        OrganizerFieldDTO,
        SessionSelfEditContext,
    )
    from ludamus.pacts.chronology import ProposalAcceptContextDTO
    from ludamus.pacts.services import ServicesProtocol


class SessionEditRequest(HttpRequest):
    context: AuthenticatedRequestContext
    services: ServicesProtocol


_SESSION_FIELD_PREFIX = "session_field"


def _session_field_pairs(
    ctx: SessionSelfEditContext,
) -> list[tuple[OrganizerFieldDTO, bool]]:
    # The modal edits an existing session rather than answering a category's
    # call for proposals, so nothing here is required.
    return [(field, False) for field, _current in ctx.session_fields]


def _collect_session_field_values(
    session_id: int, ctx: SessionSelfEditContext, form: forms.Form
) -> list[SessionFieldValueData]:
    return [
        SessionFieldValueData(
            session_id=session_id,
            field_id=field.pk,
            value=answered_value(
                prefix=_SESSION_FIELD_PREFIX, field_def=field, form=form
            ),
        )
        for field, _required in _session_field_pairs(ctx)
    ]


class SessionEditView(EventsPageRequiredMixin, LoginRequiredMixin, View):
    """Facilitator self-service editing of their own session, inline in the modal.

    Both GET (edit form) and POST (save) return the form fragment swapped into
    the open session dialog via HTMX. A non-HTMX POST falls back to a full-page
    redirect to the event so the feature degrades gracefully.
    """

    request: SessionEditRequest

    @staticmethod
    def _initial_form(ctx: SessionSelfEditContext) -> SessionEditForm:
        hours, minutes = parse_duration(ctx.session.duration)
        return SessionEditForm(
            initial={
                "title": ctx.session.title,
                "display_name": ctx.session.display_name,
                "description": ctx.session.description,
                "contact_email": ctx.session.contact_email,
                "participants_limit": ctx.session.participants_limit,
                "min_age": ctx.session.min_age,
                "duration_hours": hours or None,
                "duration_minutes": minutes or None,
                "cover_image": stored_file(
                    ctx.session.cover_image_url, ctx.session.cover_image_original_name
                ),
            }
        )

    @staticmethod
    def _fields_form(
        ctx: SessionSelfEditContext, data: QueryDict | None = None
    ) -> forms.Form:
        return dynamic_fields_form(
            prefix=_SESSION_FIELD_PREFIX,
            fields=_session_field_pairs(ctx),
            data=data,
            initial={field.slug: current for field, current in ctx.session_fields},
        )

    def get(
        self, _request: HttpRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        ctx = self._context(event_slug, session_id)
        return self._render(
            ctx=ctx,
            form=self._initial_form(ctx),
            fields_form=self._fields_form(ctx),
            saved=False,
        )

    def post(
        self, _request: HttpRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        ctx = self._context(event_slug, session_id)
        form = SessionEditForm(self.request.POST, self.request.FILES)
        if cover := stored_file(
            ctx.session.cover_image_url, ctx.session.cover_image_original_name
        ):
            form.fields["cover_image"].initial = cover
        # The fields block only posts when the modal rendered it; without the
        # marker the stored answers are left alone rather than blanked.
        submitted = self.request.POST.get("session_fields_submitted") == "1"
        fields_form = self._fields_form(ctx, self.request.POST if submitted else None)
        fields_valid = fields_form.is_valid() if submitted else True
        if not form.is_valid() or not fields_valid:
            return self._render(
                ctx=ctx, form=form, fields_form=fields_form, saved=False
            )

        field_values = (
            _collect_session_field_values(session_id, ctx, fields_form)
            if submitted
            else None
        )
        try:
            self.request.services.session_self_edit.update(
                session_id,
                self.request.context.current_user_id,
                form.cleaned_data,
                field_values,
            )
        except SessionEditNotAllowedError as exc:
            raise Http404 from exc

        if not self.request.headers.get("HX-Request"):
            event_url = reverse("web:chronology:event", kwargs={"slug": event_slug})
            return redirect(f"{event_url}?session={session_id}")
        ctx = self._context(event_slug, session_id)
        return self._render(
            ctx=ctx,
            form=self._initial_form(ctx),
            fields_form=self._fields_form(ctx),
            saved=True,
        )

    def _context(self, event_slug: str, session_id: int) -> SessionSelfEditContext:
        try:
            ctx = self.request.services.session_self_edit.get_edit_context(
                session_id, self.request.context.current_user_id
            )
        except SessionEditNotAllowedError as exc:
            raise Http404 from exc
        if ctx.event.slug != event_slug:
            raise Http404
        return ctx

    def _render(
        self,
        *,
        ctx: SessionSelfEditContext,
        form: SessionEditForm,
        fields_form: forms.Form,
        saved: bool,
    ) -> HttpResponse:
        post_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": ctx.event.slug, "session_id": ctx.session.pk},
        )
        return TemplateResponse(
            self.request,
            "chronology/parts/session-edit-form.html",
            {
                "session": ctx.session,
                "form": form,
                "field_descriptors": field_descriptors(
                    prefix=_SESSION_FIELD_PREFIX,
                    fields=_session_field_pairs(ctx),
                    form=fields_form,
                ),
                "post_url": post_url,
                "saved": saved,
            },
        )


class SessionBookmarkToggleView(EventsPageRequiredMixin, View):
    @staticmethod
    def post(request: RootRequest, session_id: int) -> JsonResponse:
        if (user_id := request.context.current_user_id) is None:
            # fetch() call, not a browser navigation — a redirect would be
            # useless, so surface the auth failure as JSON for the client.
            return JsonResponse({"error": "auth"}, status=401)
        result = request.services.bookmarks.toggle(
            user_id=user_id,
            session_id=SessionId(session_id),
            sphere_id=request.context.current_sphere_id,
        )
        if result is None:
            return JsonResponse({"error": "not-found"}, status=404)
        return JsonResponse({"bookmarked": result.bookmarked, "count": result.count})


class SessionClaimWithdrawActionView(EventsPageRequiredMixin, LoginRequiredMixin, View):
    """The author of a walk-up claim taking it back off the programme."""

    request: SessionEditRequest
    http_method_names = ("post",)

    @staticmethod
    def post(
        request: SessionEditRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        event_url = reverse("web:chronology:event", kwargs={"slug": event_slug})
        try:
            event = request.services.events.read_by_slug(
                request.context.current_sphere_id, event_slug
            )
            # The service re-reads the claim under the lock and decides who may
            # release it; which button rendered is not the check.
            request.services.timetable.release_claim(
                session_pk=session_id,
                event_pk=event.pk,
                user_pk=request.context.current_user_id,
                user_slug=request.context.current_user_slug,
            )
        except NotFoundError:
            messages.error(request, _("There is no claim here to withdraw."))
            return redirect(event_url)
        except ProposalAcceptDeniedError:
            messages.error(request, _("This claim is not yours to withdraw."))
            return redirect(event_url)

        messages.success(request, _("Claim withdrawn. The spot is free again."))
        return redirect(event_url)


class ProposalAcceptPageView(EventsPageRequiredMixin, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        context = self._load(request, event_slug, session_id)
        self._require_configured(context)
        form = self._build_form(context)()
        return self._render(request, context, form)

    def post(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        context = self._load(request, event_slug, session_id)
        form = self._build_form(context)(data=request.POST)
        if not form.is_valid():
            return self._render(request, context, form)

        try:
            request.services.proposal_acceptance.accept_session(
                session_id=context.session.pk,
                space_id=form.cleaned_data["space"],
                time_slot_id=form.cleaned_data["time_slot"],
                user_slug=request.context.current_user_slug,
                sphere_id=request.context.current_sphere_id,
            )
        except SpaceTimeConflictError:
            form.add_error(
                None, _("There is already a session scheduled at this space and time.")
            )
            return self._render(request, context, form)

        messages.success(
            request,
            _("Proposal '{}' has been accepted and added to the agenda.").format(
                context.session.title
            ),
        )
        return redirect("web:chronology:event", slug=context.event.slug)

    @staticmethod
    def _build_form(context: ProposalAcceptContextDTO) -> type[forms.Form]:
        return create_proposal_acceptance_form(
            space_options=context.space_options, time_slots=context.time_slots
        )

    @staticmethod
    def _load(
        request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> ProposalAcceptContextDTO:
        context = request.services.proposal_acceptance.get_accept_context(
            session_id=session_id,
            user_slug=request.context.current_user_slug,
            sphere_id=request.context.current_sphere_id,
        )
        if context is None or context.event.slug != event_slug:
            raise RedirectError(reverse("web:index"), error=_("Session not found."))

        event_url = reverse("web:chronology:event", kwargs={"slug": context.event.slug})
        if context.session.status != SessionStatus.PENDING:
            raise RedirectError(
                event_url, warning=_("This proposal has already been accepted.")
            )
        if not context.can_accept:
            raise RedirectError(
                event_url,
                error=_(
                    "You don't have permission to accept proposals for this event."
                ),
            )
        return context

    @staticmethod
    def _require_configured(context: ProposalAcceptContextDTO) -> None:
        event_url = reverse("web:chronology:event", kwargs={"slug": context.event.slug})
        if not context.space_options:
            raise RedirectError(
                event_url,
                error=_(
                    "No spaces configured for this event. Please create spaces first."
                ),
            )
        if not context.time_slots:
            raise RedirectError(
                event_url,
                error=_(
                    "No time slots configured for this event. "
                    "Please create time slots first."
                ),
            )

    @staticmethod
    def _render(
        request: AuthenticatedRootRequest,
        context: ProposalAcceptContextDTO,
        form: forms.Form,
    ) -> HttpResponse:
        return TemplateResponse(
            request,
            "chronology/accept_proposal.html",
            {
                "session": context.session,
                "event": context.event,
                "presenter": context.presenter,
                "time_slots": context.time_slots,
                "preferred_time_slot_ids": context.preferred_time_slot_ids,
                "form": form,
                "field_values": context.field_values,
            },
        )
