"""The signed-in home on the root sphere.

zagrajmy.net runs no programme of its own, so its root stays the pitch and
this is where a member's own activity gathers: what they hold, what is open
to them, and which spheres are worth following. Every other sphere's members
have its feed for that, so the page is root-sphere-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest


def _require_root_sphere(request: AuthenticatedRootRequest) -> None:
    if request.context.current_sphere_id != request.context.root_sphere_id:
        raise Http404


def dashboard_page(request: RootRequest, *, user_id: int) -> HttpResponse:
    """Render the signed-in home.

    Returns:
        The dashboard for ``user_id``. The id is passed rather than read off
        the request so the root sphere's front door, which has already
        established who is asking, can render this page directly.
    """
    sphere_id = request.context.current_sphere_id
    return TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "dashboard": request.services.dashboard.read(
                user_id=user_id, now=datetime.now(UTC)
            ),
            "can_create_encounter": request.services.encounters.can_create(
                sphere_id=sphere_id, user_id=user_id
            ),
        },
    )


class DashboardPageView(LoginRequiredMixin, View):
    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        _require_root_sphere(request)
        return dashboard_page(request, user_id=request.context.current_user_id)


class SphereSubscribeActionView(LoginRequiredMixin, View):
    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        _require_root_sphere(request)
        try:
            request.services.sphere_subscriptions.subscribe(
                sphere_id=pk, user_id=request.context.current_user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc
        return redirect(reverse("web:dashboard"))


class SphereUnsubscribeActionView(LoginRequiredMixin, View):
    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        _require_root_sphere(request)
        request.services.sphere_subscriptions.unsubscribe(
            sphere_id=pk, user_id=request.context.current_user_id
        )
        return redirect(reverse("web:dashboard"))


class OfferClaimActionView(LoginRequiredMixin, View):
    """Claim the seat held for this member straight from their agenda."""

    @staticmethod
    def post(request: AuthenticatedRootRequest, session_id: int) -> HttpResponse:
        _require_root_sphere(request)
        result = request.services.waitlist_promotion.claim_member_offer(
            user_id=request.context.current_user_id, session_id=session_id
        )
        # Every failure lands back on the dashboard: the lookup only ever
        # searched this member's own seats, and "not found" is as often a
        # double click or a party-mate's earlier claim as anything else.
        if result.success:
            messages.success(
                request, _("Spot claimed — you are now confirmed for this session.")
            )
        else:
            messages.error(request, _("This offer has expired or was already claimed."))
        return redirect(reverse("web:dashboard"))
