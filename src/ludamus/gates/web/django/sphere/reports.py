"""The root sphere's queue of content reports, and deciding one."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.forms import ReportDecisionForm
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts import NotFoundError
from ludamus.pacts.report import ReportAlreadyDecidedError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts.report import ContentReportDTO


def _read(request: MultiverseRequest, pk: int) -> ContentReportDTO:
    try:
        return request.services.report_queue.read(
            sphere_id=request.context.current_sphere_id,
            root_sphere_id=request.context.root_sphere_id,
            report_id=pk,
        )
    except NotFoundError as exc:
        raise Http404 from exc


def _render_detail(
    request: MultiverseRequest,
    report: ContentReportDTO,
    form: ReportDecisionForm | None,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> TemplateResponse:
    return TemplateResponse(
        request,
        "multiverse/panel/content_reports/detail.html",
        {
            **sphere_sidebar_context(request, active_nav="reports"),
            "report": report,
            "form": form,
        },
        status=status,
    )


class ReportsPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        try:
            reports = self.request.services.report_queue.list_open(
                sphere_id=self.request.context.current_sphere_id,
                root_sphere_id=self.request.context.root_sphere_id,
            )
        except NotFoundError as exc:
            raise Http404 from exc
        return TemplateResponse(
            self.request,
            "multiverse/panel/content_reports/list.html",
            {
                **sphere_sidebar_context(self.request, active_nav="reports"),
                "reports": reports,
            },
        )


class ReportDetailPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        report = _read(self.request, pk)
        form = None if report.decided_at else ReportDecisionForm()
        return _render_detail(self.request, report, form)


class ReportDecideActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        form = ReportDecisionForm(self.request.POST)
        if not form.is_valid():
            return _render_detail(
                self.request,
                _read(self.request, pk),
                form,
                status=HTTPStatus.BAD_REQUEST,
            )
        try:
            decided = self.request.services.report_queue.decide(
                sphere_id=self.request.context.current_sphere_id,
                root_sphere_id=self.request.context.root_sphere_id,
                report_id=pk,
                decided_by_id=self.request.context.current_user_id,
                decision=form.cleaned_data["decision"],
            )
        except NotFoundError as exc:
            raise Http404 from exc
        except ReportAlreadyDecidedError:
            messages.error(
                self.request,
                _("Someone already decided this report. Their decision stands."),
            )
            return redirect("multiverse:panel:report-detail", pk=pk)
        messages.success(
            self.request,
            (
                _("Report decided. We emailed the reporter your decision.")
                if decided.reporter_email
                else _("Report decided. The reporter left no email to send it to.")
            ),
        )
        return redirect("multiverse:panel:reports")
