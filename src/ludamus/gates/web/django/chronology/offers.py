from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.generic.base import View

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest


class SessionOfferClaimView(View):
    """Login-free claim of an offered waiting-list spot via its token link.

    Works for anonymous waiters (the token is the credential). GET shows the
    offer; POST claims the whole party.
    """

    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        offer = request.services.waitlist_promotion.peek_offer(token=token)
        if offer is None:
            messages.error(
                request, _("This offer is no longer available or has expired.")
            )
            return redirect("web:events")
        return TemplateResponse(
            request, "chronology/offer_claim.html", {"offer": offer, "token": token}
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        result = request.services.waitlist_promotion.claim_offer(token=token)
        if result.success and result.event_slug:
            messages.success(
                request, _("Spot claimed — you are now confirmed for this session.")
            )
            return redirect("web:chronology:event", slug=result.event_slug)
        messages.error(request, _("This offer has expired or was already claimed."))
        return redirect("web:events")


class SessionOfferDeclineView(View):
    """Login-free decline of an offered spot via its token link.

    The way out of a seat held by a party leader (or an unwanted waitlist
    offer): drops the offered rows and rolls the freed seats on.
    """

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        result = request.services.waitlist_promotion.decline_offer(token=token)
        if result.success and result.event_slug:
            messages.success(request, _("Offer declined — the seat was released."))
            return redirect("web:chronology:event", slug=result.event_slug)
        messages.error(request, _("This offer is no longer available or has expired."))
        return redirect("web:events")


class NotificationsMarkReadView(LoginRequiredMixin, View):
    """POST: mark all of the current user's notifications as read."""

    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        request.services.notifications.mark_all_read(request.context.current_user_id)
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return redirect(next_url)
        return redirect("web:index")
