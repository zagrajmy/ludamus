"""The public report form: anyone may report content as illegal (DSA Art. 16).

A page links here with the content's kind and id, and `from` naming the page
the report starts on, which becomes the report's location.
"""

from __future__ import annotations

from http import HTTPStatus
from types import MappingProxyType
from typing import TYPE_CHECKING

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.pacts import NotFoundError
from ludamus.pacts.report import (
    REPORT_EXPLANATION_MAX_LENGTH,
    REPORT_LOCATION_MAX_LENGTH,
    REPORTER_NAME_MAX_LENGTH,
    ReportedContentKind,
    ReportRateLimitedError,
    ReportReason,
    ReportSubmission,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.report import ReportFormDTO

REASON_LABELS: Mapping[ReportReason, _StrPromise] = MappingProxyType(
    {
        ReportReason.CHILD_SEXUAL_ABUSE: gettext_lazy("Child sexual abuse material"),
        ReportReason.THREATS: gettext_lazy(
            "Threats, harassment or incitement to violence"
        ),
        ReportReason.HATE_SPEECH: gettext_lazy("Illegal hate speech"),
        ReportReason.PRIVACY: gettext_lazy(
            "Someone's personal data shared without consent"
        ),
        ReportReason.SCAM: gettext_lazy("Fraud or scam"),
        ReportReason.INTELLECTUAL_PROPERTY: gettext_lazy(
            "Copyright or trademark infringement"
        ),
        ReportReason.OTHER: gettext_lazy("Other illegal content"),
    }
)

KIND_LABELS: Mapping[ReportedContentKind, _StrPromise] = MappingProxyType(
    {
        ReportedContentKind.SESSION: gettext_lazy("session"),
        ReportedContentKind.USER: gettext_lazy("user profile"),
    }
)


class ContentReportForm(forms.Form):
    reason = forms.ChoiceField(
        label=gettext_lazy("Why is it illegal?"),
        choices=[(reason.value, label) for reason, label in REASON_LABELS.items()],
        widget=forms.RadioSelect,
    )
    explanation = forms.CharField(
        label=gettext_lazy("Explain what is illegal and why"),
        help_text=gettext_lazy(
            "Point to what in the content breaks the law, as precisely as you can."
        ),
        max_length=REPORT_EXPLANATION_MAX_LENGTH,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    reporter_name = forms.CharField(
        label=gettext_lazy("Your name"),
        required=False,
        max_length=REPORTER_NAME_MAX_LENGTH,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    reporter_email = forms.EmailField(
        label=gettext_lazy("Your email"),
        required=False,
        help_text=gettext_lazy(
            "We send the receipt and our decision here. Name and email may be "
            "left out only for reports of child sexual abuse material."
        ),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    good_faith = forms.BooleanField(
        label=gettext_lazy(
            "I believe in good faith that the information in this report is "
            "accurate and complete."
        )
    )

    def clean(self) -> dict[str, str | bool]:
        cleaned: dict[str, str | bool] = super().clean() or {}
        reason = cleaned.get("reason")
        if reason and ReportReason(str(reason)).requires_contact:
            if not cleaned.get("reporter_name"):
                self.add_error(
                    "reporter_name",
                    _(
                        "Enter your name. Only reports of child sexual abuse "
                        "material can be sent without it."
                    ),
                )
            if (
                not cleaned.get("reporter_email")
                and "reporter_email" not in self.errors
            ):
                self.add_error(
                    "reporter_email",
                    _(
                        "Enter your email, so we can send you the receipt and "
                        "our decision."
                    ),
                )
        return cleaned


def _parse_kind(kind: str) -> ReportedContentKind:
    try:
        return ReportedContentKind(kind)
    except ValueError as exc:
        raise Http404 from exc


def _origin_path(request: RootRequest, candidate: str) -> str:
    # Only a path on this host: `from` is in the link, so anyone can set it.
    is_local = candidate.startswith("/") and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}
    )
    if (
        is_local
        and len(request.build_absolute_uri(candidate)) <= REPORT_LOCATION_MAX_LENGTH
    ):
        return candidate
    return ""


class ReportPageView(View):
    request: RootRequest

    def get(self, request: RootRequest, kind: str, object_id: int) -> HttpResponse:
        page = self._prepare(_parse_kind(kind), object_id)
        origin = _origin_path(request, request.GET.get("from", ""))
        form = ContentReportForm(
            initial={
                "reporter_name": page.reporter.name,
                "reporter_email": page.reporter.email,
            }
        )
        return self._render(page, form, origin=origin)

    def post(self, request: RootRequest, kind: str, object_id: int) -> HttpResponse:
        page = self._prepare(_parse_kind(kind), object_id)
        form = ContentReportForm(request.POST)
        origin = _origin_path(request, request.POST.get("from", ""))
        if not form.is_valid():
            return self._render(
                page, form, origin=origin, status=HTTPStatus.BAD_REQUEST
            )
        data = form.cleaned_data
        try:
            report = request.services.reports.submit(
                ReportSubmission(
                    kind=page.target.kind,
                    object_id=page.target.object_id,
                    sphere_id=request.context.current_sphere_id,
                    reason=ReportReason(data["reason"]),
                    explanation=data["explanation"],
                    reporter_name=data["reporter_name"],
                    reporter_email=data["reporter_email"],
                    reporter_user_id=request.context.current_user_id,
                    location=request.build_absolute_uri(origin) if origin else "",
                    good_faith=data["good_faith"],
                ),
                client_ip=get_client_ip(request),
            )
        except ReportRateLimitedError:
            form.add_error(
                None,
                _(
                    "You have sent several reports in the last hour. Try again "
                    "later, or write to %(support)s."
                )
                % {"support": settings.SUPPORT_EMAIL},
            )
            return self._render(
                page, form, origin=origin, status=HTTPStatus.TOO_MANY_REQUESTS
            )
        messages.success(
            request,
            (
                _("Report sent. We emailed you a receipt.")
                if report.reporter_email
                else _("Report sent. Thank you.")
            ),
        )
        return redirect(origin or page.target.location)

    def _prepare(self, kind: ReportedContentKind, object_id: int) -> ReportFormDTO:
        try:
            return self.request.services.reports.prepare(
                kind=kind,
                object_id=object_id,
                sphere_id=self.request.context.current_sphere_id,
                reporter_user_id=self.request.context.current_user_id,
            )
        except NotFoundError as exc:
            raise Http404 from exc

    def _render(
        self,
        page: ReportFormDTO,
        form: ContentReportForm,
        *,
        origin: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> TemplateResponse:
        return TemplateResponse(
            self.request,
            "report/form.html",
            {
                "target": page.target,
                "kind_label": KIND_LABELS[page.target.kind],
                "form": form,
                "origin": origin,
                "back_url": origin or page.target.location,
            },
            status=status,
        )
