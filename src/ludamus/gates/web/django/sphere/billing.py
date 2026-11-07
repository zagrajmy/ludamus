"""The sphere's Plan & payouts page: its deal with Zagrajmy, and its Stripe account.

Two money flows, one page. Payouts is where ticket money lands (the sphere's
own connected Stripe account); the plan is what the sphere pays Zagrajmy and
what it gets for it. Every action hands the browser to Stripe and Stripe hands
it back here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.helpers import account_email
from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.multiverse import Capability
from ludamus.pacts.payment_api import PaymentProviderError
from ludamus.pacts.tickets import PayoutStatus

if TYPE_CHECKING:
    from django.http import HttpResponse

logger = logging.getLogger(__name__)

_BILLING_URL = "multiverse:panel:billing"


def _absolute(request: MultiverseRequest, name: str) -> str:
    return request.build_absolute_uri(reverse(name))


def _stripe_unreachable(request: MultiverseRequest, what: str) -> HttpResponse:
    logger.warning(
        "Billing: Stripe %s failed for sphere=%s",
        what,
        request.context.current_sphere_id,
    )
    messages.error(
        request, _("Stripe didn't respond. Nothing was changed; try again in a moment.")
    )
    return redirect(_BILLING_URL)


class BillingPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        return TemplateResponse(
            self.request,
            "multiverse/panel/billing.html",
            {
                **sphere_sidebar_context(self.request, active_nav="billing"),
                "plan": self.request.services.plan.page(sphere_id=sphere_id),
                "payouts": self.request.services.payouts.page(sphere_id=sphere_id),
                # Comms people read where the money goes; only managers move it.
                "can_manage": panel_access(self.request).allows(Capability.PANEL_WRITE),
            },
        )


class _ManagerOnlyMixin(SphereAccessMixin):
    # Stripe sends the browser back with a GET, which SphereAccessMixin lets
    # any sphere role through; these GETs move money settings, so they need
    # the write capability whatever the method.
    def test_func(self) -> bool:
        return panel_access(self.request).allows(Capability.PANEL_WRITE)


class BillingConnectActionView(SphereAccessMixin, View):
    """Create the sphere's Stripe account if it has none, then onboard it."""

    request: MultiverseRequest
    http_method_names = ("post",)

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        if not (email := account_email(self.request)):
            messages.error(
                self.request,
                _("Add an email address to your profile first: Stripe needs one."),
            )
            return redirect(_BILLING_URL)
        try:
            url = self.request.services.payouts.onboarding_url(
                sphere_id=self.request.context.current_sphere_id,
                email=email,
                refresh_url=_absolute(self.request, "multiverse:panel:billing-resume"),
                return_url=_absolute(self.request, "multiverse:panel:billing-return"),
            )
        except PaymentProviderError:
            return _stripe_unreachable(self.request, "onboarding")
        logger.info(
            "Billing: onboarding started for sphere=%s by=%s",
            self.request.context.current_sphere_id,
            self.request.context.current_user_id,
        )
        return redirect(url)


class BillingResumeActionView(_ManagerOnlyMixin, View):
    """Where Stripe sends a manager whose onboarding link went stale.

    A GET, because Stripe can only redirect, so it creates nothing: a sphere
    with an account gets a fresh link to it, one without goes back to the page.
    """

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        try:
            url = self.request.services.payouts.resume_onboarding_url(
                sphere_id=self.request.context.current_sphere_id,
                refresh_url=_absolute(self.request, "multiverse:panel:billing-resume"),
                return_url=_absolute(self.request, "multiverse:panel:billing-return"),
            )
        except PaymentProviderError:
            return _stripe_unreachable(self.request, "onboarding")
        return redirect(url or _BILLING_URL)


class BillingReturnActionView(_ManagerOnlyMixin, View):
    """Where Stripe's onboarding hands the manager back."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        try:
            page = self.request.services.payouts.refresh(
                sphere_id=self.request.context.current_sphere_id
            )
        except PaymentProviderError:
            return _stripe_unreachable(self.request, "account refresh")
        logger.info(
            "Billing: onboarding returned for sphere=%s status=%s",
            self.request.context.current_sphere_id,
            page.status,
        )
        if page.status is PayoutStatus.ACTIVE:
            messages.success(
                self.request, _("Stripe is connected. You can sell tickets now.")
            )
        else:
            messages.info(
                self.request,
                _(
                    "Stripe still needs a few details. Continue the setup whenever"
                    " you have them at hand."
                ),
            )
        return redirect(_BILLING_URL)


class BillingPortalActionView(SphereAccessMixin, View):
    request: MultiverseRequest
    http_method_names = ("post",)

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        try:
            url = self.request.services.plan.billing_portal_url(
                sphere_id=self.request.context.current_sphere_id,
                return_url=_absolute(self.request, _BILLING_URL),
            )
        except NotFoundError:
            messages.error(self.request, _("This sphere has no billing history yet."))
            return redirect(_BILLING_URL)
        except PaymentProviderError:
            return _stripe_unreachable(self.request, "billing portal")
        return redirect(url)
