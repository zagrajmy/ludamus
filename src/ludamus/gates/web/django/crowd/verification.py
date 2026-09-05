"""Email-verification pages: confirm, cancel, resend, invalid-link.

GET renders and changes nothing — mail scanners prefetch links, so only a
CSRF-protected POST consumes one. One route serves both actions: the action is
signed into the token, so the token alone picks the page and decides what
redeeming it does.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, assert_never

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


class EmailLinkPageView(View):
    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        if (link := request.services.email_verification.describe(token)) is None:
            return _invalid_link_page(request)
        match link.action:
            case EmailVerificationAction.CONFIRM:
                template_name = "crowd/email/confirm.html"
            case EmailVerificationAction.CANCEL:
                template_name = "crowd/email/cancel.html"
            case _:
                assert_never(link.action)
        return TemplateResponse(
            request, template_name, {"address": link.address, "token": token}
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        # `redeem` reports the signed action, so POST resolves the token once.
        result = request.services.email_verification.redeem(token)
        logger.info(
            "Email link redeemed: action=%s outcome=%s", result.action, result.outcome
        )
        # match + assert_never (not an enum-keyed dict) so a new RedeemOutcome
        # fails type-checking instead of a user's request.
        match result.outcome:
            case RedeemOutcome.ADDRESS_TAKEN:
                return _invalid_link_page(request, address_taken=True)
            case RedeemOutcome.EXPIRED | RedeemOutcome.ALREADY_USED:
                return _invalid_link_page(request)
            case RedeemOutcome.VERIFIED:
                messages.success(request, _("Your email address is verified."))
            case RedeemOutcome.CHANGE_APPLIED:
                messages.success(request, _("Your new email address is now active."))
            case RedeemOutcome.CANCELLED:
                messages.success(request, _("The email change has been cancelled."))
            case _:
                assert_never(result.outcome)
        return redirect("web:index")


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
