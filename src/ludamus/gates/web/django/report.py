"""The notice of illegal content anyone can send (DSA Art. 16)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django import forms
from django.conf import settings
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.pacts.moderation import (
    NOTICE_EXPLANATION_MAX_LENGTH,
    NOTICE_NAME_MAX_LENGTH,
    NOTICE_URL_MAX_LENGTH,
    ContentNoticeData,
    NoticeCategory,
    NoticeOutcome,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest

_SENT_REFERENCE = re.compile(r"Z-\d{1,12}")
_CATEGORY_LABELS = {
    NoticeCategory.CHILD_SEXUAL_ABUSE: _("Child sexual abuse material"),
    NoticeCategory.CHILD_SAFETY: _("Grooming or other danger to a child"),
    NoticeCategory.THREATS_OR_HATE: _("Threats, incitement to violence or hate"),
    NoticeCategory.HARASSMENT: _("Harassment, stalking or defamation"),
    NoticeCategory.PRIVACY: _(
        "Someone's personal data or image shared without consent"
    ),
    NoticeCategory.INTELLECTUAL_PROPERTY: _("Copyright or trademark infringement"),
    NoticeCategory.FRAUD: _("Fraud, scam or phishing"),
    NoticeCategory.OTHER: _("Other illegal content"),
}


class ContentNoticeForm(forms.Form):
    url = forms.URLField(
        label=_("Address of the content"),
        max_length=NOTICE_URL_MAX_LENGTH,
        assume_scheme="https",
        help_text=_(
            "Copy it from your browser's address bar, or use a message's"
            " “Copy message link”."
        ),
    )
    category = forms.ChoiceField(
        label=_("What is wrong with it"),
        choices=[("", "---------"), *_CATEGORY_LABELS.items()],
    )
    explanation = forms.CharField(
        label=_("Why it is illegal"),
        max_length=NOTICE_EXPLANATION_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=_(
            "Say what the content shows or says and why you think it breaks the"
            " law. On a long page, point to the exact place."
        ),
    )
    reporter_name = forms.CharField(
        label=_("Your name"), max_length=NOTICE_NAME_MAX_LENGTH, required=False
    )
    reporter_email = forms.EmailField(
        label=_("Your email"),
        required=False,
        help_text=_(
            "We confirm the report and send the decision here. Name and email may"
            " be left out only when the report is about the sexual abuse or"
            " grooming of a child."
        ),
    )
    good_faith = forms.BooleanField(
        label=_(
            "I am making this report in good faith, and what I wrote is accurate"
            " and complete."
        )
    )


class ReportPageView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        if _SENT_REFERENCE.fullmatch(sent := request.GET.get("sent", "")):
            return _page(request, form=None, sent_reference=sent)
        url = request.GET.get("url", "")[:NOTICE_URL_MAX_LENGTH]
        return _page(
            request, form=ContentNoticeForm(initial={"url": url}), sent_reference=""
        )

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        form = ContentNoticeForm(request.POST)
        if not form.is_valid():
            return _page(request, form=form, sent_reference="")
        data = form.cleaned_data
        submission = request.services.notices.submit(
            ContentNoticeData(
                url=data["url"],
                category=NoticeCategory(data["category"]),
                explanation=data["explanation"],
                reporter_name=data["reporter_name"],
                reporter_email=data["reporter_email"],
                reporter_id=request.context.current_user_id,
                sphere_id=request.context.current_sphere_id,
                language=get_language(),
            ),
            ip_address=get_client_ip(request),
        )
        match submission.outcome:
            case NoticeOutcome.CREATED:
                query = urlencode({"sent": submission.case_reference})
                return redirect(f"{reverse('report')}?{query}")
            case NoticeOutcome.CONTACT_REQUIRED:
                if not data["reporter_name"].strip():
                    form.add_error("reporter_name", _("Enter your name."))
                if not data["reporter_email"].strip():
                    form.add_error("reporter_email", _("Enter your email."))
            case NoticeOutcome.THROTTLED:
                form.add_error(
                    None,
                    _(
                        "You sent several reports in a short time. Try again in an"
                        " hour, or write to %(email)s."
                    )
                    % {"email": settings.STAFF_EMAIL},
                )
        return _page(request, form=form, sent_reference="")


def _page(
    request: RootRequest, *, form: ContentNoticeForm | None, sent_reference: str
) -> HttpResponse:
    return TemplateResponse(
        request,
        "report.html",
        {
            "form": form,
            "sent_reference": sent_reference,
            "staff_email": settings.STAFF_EMAIL,
        },
    )
