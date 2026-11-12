"""The staff cases inbox: every report, notice, email and appeal, staff only.

Anyone who is not staff gets a 404, as if the pages were not there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.pages import CONTENT_DIR
from ludamus.gates.web.django.staff.forms import (
    GROUND_LABELS,
    AssignForm,
    DecisionForm,
    ReplyForm,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.staff_cases import (
    ModerationAction,
    ModerationGround,
    StaffCaseError,
    StaffCaseStatus,
)

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.staff_cases import StaffCaseDetailDTO, StaffInboxDTO

_FAQ = CONTENT_DIR / "moderation-faq.md"
_TABS = (
    (StaffCaseStatus.OPEN, "inbox"),
    (StaffCaseStatus.WAITING, "clock"),
    (StaffCaseStatus.CLOSED, "check-circle"),
)
_ERRORS = {
    "invalid_body": gettext_lazy("Write the reply first."),
    "no_recipient": gettext_lazy(
        "This case has no address to answer. Add a note instead."
    ),
    "invalid_assignee": gettext_lazy("Pick someone on staff."),
    "same_decider": gettext_lazy(
        "You made the decision under appeal. Someone else decides it."
    ),
}


def _faq() -> str:
    return _FAQ.read_text(encoding="utf-8")


def _status(request: HttpRequest) -> StaffCaseStatus:
    try:
        return StaffCaseStatus(request.GET.get("status", StaffCaseStatus.OPEN))
    except ValueError:
        return StaffCaseStatus.OPEN


class _Tab(TypedDict):
    key: str
    icon: str
    label: str
    count: int
    active: bool


class _Statement(TypedDict):
    action: ModerationAction
    ground: _StrPromise


def _tabs(inbox: StaffInboxDTO) -> list[_Tab]:
    labels = {
        StaffCaseStatus.OPEN: _("Open"),
        StaffCaseStatus.WAITING: _("Waiting"),
        StaffCaseStatus.CLOSED: _("Closed"),
    }
    return [
        {
            "key": status.value,
            "icon": icon,
            "label": labels[status],
            "count": inbox.counts.get(status, 0),
            "active": status == inbox.status,
        }
        for status, icon in _TABS
    ]


class _StaffGate(View):
    """404 before anything else for anyone signed out; the service checks staff."""

    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: str, **kwargs: int
    ) -> HttpResponseBase:
        if self.request.context.current_user_id is None:
            raise Http404
        try:
            return super().dispatch(request, *args, **kwargs)
        except NotFoundError as error:
            raise Http404 from error


def _page(
    request: AuthenticatedRootRequest,
    *,
    detail: StaffCaseDetailDTO | None,
    status: StaffCaseStatus,
    reply_form: ReplyForm | None = None,
    decision_form: DecisionForm | None = None,
) -> TemplateResponse:
    user_id = request.context.current_user_id
    inbox = request.services.staff_cases.inbox(actor_id=user_id, status=status)
    inbox_context = {"inbox": inbox, "tabs": _tabs(inbox), "faq": _faq()}
    if detail is None:
        return TemplateResponse(
            request, "staff/cases.html", {**inbox_context, "detail": None}
        )
    decision_form = decision_form or DecisionForm(
        request.GET if "action" in request.GET else None
    )
    return TemplateResponse(
        request,
        "staff/cases.html",
        {
            **inbox_context,
            "detail": detail,
            "reply_form": reply_form or ReplyForm(),
            "assign_form": AssignForm(
                staff=detail.staff, assignee_id=detail.case.assignee_id
            ),
            "decision_form": decision_form,
            "statement": _statement(decision_form),
        },
    )


def _statement(form: DecisionForm) -> _Statement:
    """Tell what the author would read: the action and ground picked, or defaults."""
    action, ground = form.fields["action"].initial, form.fields["ground"].initial
    if form.is_bound and form.is_valid():
        action, ground = form.cleaned_data["action"], form.cleaned_data["ground"]
    return {
        "action": ModerationAction(action),
        "ground": GROUND_LABELS[ModerationGround(ground)],
    }


class StaffCasesPageView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        return _page(request, detail=None, status=_status(request))


class StaffCasePageView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        detail = request.services.staff_cases.read(
            actor_id=request.context.current_user_id, case_id=pk
        )
        return _page(request, detail=detail, status=detail.case.status)


class StaffCaseReplyActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        user_id = request.context.current_user_id
        form = ReplyForm(request.POST)
        by_email = request.POST.get("send") == "email"
        if not form.is_valid():
            detail = request.services.staff_cases.read(actor_id=user_id, case_id=pk)
            return _page(
                request, detail=detail, status=detail.case.status, reply_form=form
            )
        try:
            request.services.staff_cases.reply(
                actor_id=user_id,
                case_id=pk,
                body=form.cleaned_data["body"],
                by_email=by_email,
            )
        except StaffCaseError as error:
            messages.error(request, _ERRORS[error.code])
        else:
            messages.success(
                request,
                _("Reply sent.") if by_email else _("Note added to the thread."),
            )
        return redirect("web:staff:case", pk=pk)


class StaffCaseAssignActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        user_id = request.context.current_user_id
        detail = request.services.staff_cases.read(actor_id=user_id, case_id=pk)
        form = AssignForm(request.POST, staff=detail.staff)
        if not form.is_valid():
            messages.error(request, _ERRORS["invalid_assignee"])
            return redirect("web:staff:case", pk=pk)
        try:
            request.services.staff_cases.assign(
                actor_id=user_id, case_id=pk, assignee_id=form.cleaned_data["assignee"]
            )
        except StaffCaseError as error:
            messages.error(request, _ERRORS[error.code])
        else:
            messages.success(request, _("Case assigned."))
        return redirect("web:staff:case", pk=pk)


class StaffCaseDecideActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        user_id = request.context.current_user_id
        form = DecisionForm(request.POST)
        if not form.is_valid():
            detail = request.services.staff_cases.read(actor_id=user_id, case_id=pk)
            return _page(
                request, detail=detail, status=detail.case.status, decision_form=form
            )
        try:
            request.services.staff_cases.decide(
                actor_id=user_id,
                case_id=pk,
                action=ModerationAction(form.cleaned_data["action"]),
                ground=ModerationGround(form.cleaned_data["ground"]),
            )
        except StaffCaseError as error:
            messages.error(request, _ERRORS[error.code])
        else:
            messages.success(request, _("Decision recorded. The case is closed."))
        return redirect("web:staff:case", pk=pk)
