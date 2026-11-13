"""The staff cases inbox: every notice, chat report and email, staff only.

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
from ludamus.gates.web.django.staff.forms import AssignForm, DecisionForm, ReplyForm
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    InvalidVerdictError,
    ModerationDecision,
    ModerationGround,
)
from ludamus.pacts.staff_cases import CaseStatus, StaffCaseError, StaffDecision

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.staff_cases import CaseDetailDTO, StaffInboxDTO

_FAQ = CONTENT_DIR / "moderation-faq.md"
_TABS = (
    (CaseStatus.OPEN, "inbox"),
    (CaseStatus.WAITING, "clock"),
    (CaseStatus.CLOSED, "check-circle"),
)
_ERRORS = {
    "invalid_body": gettext_lazy("Write the reply first."),
    "no_recipient": gettext_lazy(
        "Nobody outside the team wrote in this case. Add a note instead."
    ),
    "invalid_assignee": gettext_lazy("Pick someone on staff."),
    "nothing_to_decide": gettext_lazy(
        "Nothing in this case is waiting for a decision."
    ),
    "undecided": gettext_lazy("Decide the case's reports before closing it."),
    "no_notice": gettext_lazy("Only a notice names the account it is about."),
    "unknown_account": gettext_lazy(
        "No single account matches. Give its username, slug or email."
    ),
    "chat_unavailable": gettext_lazy(
        "The chat did not answer, so nothing was removed or decided. Try again."
    ),
}
_DEFAULT_DECISION = StaffDecision(
    decision=ModerationDecision.CONTENT_REMOVED,
    ground=ModerationGround.TERMS_UNLAWFUL_CONTENT,
    decision_text="",
)


class _Tab(TypedDict):
    key: str
    icon: str
    label: str
    count: int
    active: bool


def _tabs(inbox: StaffInboxDTO) -> list[_Tab]:
    labels = {
        CaseStatus.OPEN: _("Open"),
        CaseStatus.WAITING: _("Waiting"),
        CaseStatus.CLOSED: _("Closed"),
    }
    return [
        {
            "key": status.value,
            "icon": icon,
            "label": labels[status],
            "count": inbox.counts[status],
            "active": status == inbox.status,
        }
        for status, icon in _TABS
    ]


def _status(request: HttpRequest) -> CaseStatus:
    try:
        return CaseStatus(request.GET.get("status", CaseStatus.OPEN))
    except ValueError:
        return CaseStatus.OPEN


def _case_url(pk: int) -> HttpResponse:
    return redirect("web:staff:case", pk=pk)


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
    detail: CaseDetailDTO | None,
    status: CaseStatus,
    reply_form: ReplyForm | None = None,
    decision_form: DecisionForm | None = None,
) -> TemplateResponse:
    services = request.services.staff_cases
    inbox = services.inbox(actor_id=request.context.current_user_id, status=status)
    inbox_context = {
        "inbox": inbox,
        "tabs": _tabs(inbox),
        "faq": _FAQ.read_text(encoding="utf-8"),
    }
    if detail is None:
        return TemplateResponse(
            request, "staff/cases.html", {**inbox_context, "detail": None}
        )
    if decision_form is None:
        decision_form = DecisionForm(request.GET if "decision" in request.GET else None)
    shown = (
        decision_form.staff_decision()
        if decision_form.is_valid()
        else _DEFAULT_DECISION
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
            "statement": services.preview(shown),
        },
    )


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
        return _case_url(pk)


class StaffCaseAssignActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        user_id = request.context.current_user_id
        detail = request.services.staff_cases.read(actor_id=user_id, case_id=pk)
        form = AssignForm(request.POST, staff=detail.staff)
        if not form.is_valid():
            messages.error(request, _ERRORS["invalid_assignee"])
            return _case_url(pk)
        request.services.staff_cases.assign(
            actor_id=user_id, case_id=pk, assignee_id=form.cleaned_data["assignee"]
        )
        messages.success(request, _("Case assigned."))
        return _case_url(pk)


class StaffCaseCloseActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            request.services.staff_cases.close(
                actor_id=request.context.current_user_id, case_id=pk
            )
        except StaffCaseError as error:
            messages.error(request, _ERRORS[error.code])
        else:
            messages.success(request, _("Case closed."))
        return _case_url(pk)


class StaffCaseDecideActionView(_StaffGate):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        user_id = request.context.current_user_id
        form = DecisionForm(request.POST)
        if form.is_valid():
            try:
                request.services.staff_cases.decide(
                    actor_id=user_id, case_id=pk, decision=form.staff_decision()
                )
            except InvalidVerdictError as error:
                form.add_error(
                    None,
                    _("This decision is incomplete: %(reason)s") % {"reason": error},
                )
            except StaffCaseError as error:
                messages.error(request, _ERRORS[error.code])
                return _case_url(pk)
            else:
                messages.success(request, _("Decision recorded. The case is closed."))
                return _case_url(pk)
        detail = request.services.staff_cases.read(actor_id=user_id, case_id=pk)
        return _page(
            request, detail=detail, status=detail.case.status, decision_form=form
        )
