"""Email-verification pages: confirm, cancel, resend, invalid-link.

GET renders and changes nothing — mail scanners prefetch links, so only a
CSRF-protected POST consumes one. The action is signed into the token; the
URL path merely picks the page, and a mismatch lands on the invalid page.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.pacts.crowd import (
    EmailVerificationAction,
    RedeemOutcome,
    VerificationRequestOutcome,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest

logger = logging.getLogger(__name__)


def _invalid_link_page(
    request: RootRequest, *, address_taken: bool = False
) -> TemplateResponse:
    return TemplateResponse(
        request, "crowd/email/link_invalid.html", {"address_taken": address_taken}
    )


class _EmailLinkPageView(View):
    expected_action: ClassVar[EmailVerificationAction]
    template_name: ClassVar[str]

    def get(self, request: RootRequest, token: str) -> HttpResponse:
        link = request.services.email_verification.describe(token)
        if link is None or link.action != self.expected_action:
            return _invalid_link_page(request)
        return TemplateResponse(
            request, self.template_name, {"address": link.address, "token": token}
        )

    def post(self, request: RootRequest, token: str) -> HttpResponse:
        link = request.services.email_verification.describe(token)
        if link is None or link.action != self.expected_action:
            return _invalid_link_page(request)
        outcome = request.services.email_verification.redeem(token)
        logger.info("Email link redeemed: action=%s outcome=%s", link.action, outcome)
        if outcome == RedeemOutcome.ADDRESS_TAKEN:
            return _invalid_link_page(request, address_taken=True)
        if outcome in {RedeemOutcome.EXPIRED, RedeemOutcome.ALREADY_USED}:
            return _invalid_link_page(request)
        messages.success(
            request,
            {
                RedeemOutcome.VERIFIED: _("Your email address is verified."),
                RedeemOutcome.CHANGE_APPLIED: _(
                    "Your new email address is now active."
                ),
                RedeemOutcome.CANCELLED: _("The email change has been cancelled."),
            }[outcome],
        )
        return redirect("web:index")


class EmailConfirmPageView(_EmailLinkPageView):
    expected_action = EmailVerificationAction.CONFIRM
    template_name = "crowd/email/confirm.html"


class EmailCancelPageView(_EmailLinkPageView):
    expected_action = EmailVerificationAction.CANCEL
    template_name = "crowd/email/cancel.html"


class EmailResendActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        outcome = request.services.email_verification.request_verification(
            request.context.current_user_slug
        )
        logger.info("Verification resend requested: outcome=%s", outcome)
        if outcome == VerificationRequestOutcome.SENT:
            messages.success(request, _("Verification email sent."))
        elif outcome == VerificationRequestOutcome.THROTTLED:
            messages.info(
                request,
                _(
                    "A verification email was sent a moment ago — "
                    "try again in a few minutes."
                ),
            )
        else:
            messages.info(request, _("Your email address needs no verification."))
        return redirect("web:crowd:profile")
