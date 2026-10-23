from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.template.response import TemplateResponse
from django.views.generic.base import View

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


class ProfileTicketsPageView(LoginRequiredMixin, View):
    """The tickets the signed-in person holds for this sphere's events."""

    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        return TemplateResponse(
            request,
            "crowd/user/tickets.html",
            {
                "profile_active_tab": "tickets",
                "tickets": request.services.ticket_sales.owned_tickets(
                    sphere_id=request.context.current_sphere_id,
                    holder_id=request.context.current_user_id,
                ),
            },
        )
