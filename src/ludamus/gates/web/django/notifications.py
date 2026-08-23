from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.panel import pagination_context

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


class NotificationsPageView(LoginRequiredMixin, View):
    """The full, paginated notification history — reached on purpose ("View all")."""

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        notifications = request.services.notifications.list_for_user(
            request.context.current_user_id
        )
        pagination = pagination_context(request, notifications)
        return TemplateResponse(
            request,
            "notifications/index.html",
            {
                "notifications": list(pagination["page_obj"].object_list),
                "active_nav": "notifications",
                **pagination,
            },
        )


class NotificationOpenView(LoginRequiredMixin, View):
    """Mark a destination notification read, then forward to where it points."""

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        notification = request.services.notifications.open(
            request.context.current_user_id, pk
        )
        if notification is None:
            raise Http404
        if notification.url:
            return redirect(notification.url)
        # Content notifications have no url; with JS the overlay intercepts before
        # this view is ever hit, so this is the no-JS fallback: land on the list.
        return redirect("web:notifications")


class NotificationModalComponentView(LoginRequiredMixin, View):
    """Return the overlay dialog for a content notification, marking it read."""

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        notification = request.services.notifications.open(
            request.context.current_user_id, pk
        )
        if notification is None:
            raise Http404
        return TemplateResponse(
            request, "notifications/parts/modal.html", {"notification": notification}
        )
