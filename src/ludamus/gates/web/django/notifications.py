from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.pagination import windowed_pagination_context
from ludamus.gates.web.django.redirects import safe_url

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


class NotificationsPageView(LoginRequiredMixin, View):
    """The full, paginated notification history — reached on purpose ("View all")."""

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        user_id = request.context.current_user_id
        notifications = request.services.notifications
        pagination = windowed_pagination_context(
            request,
            total=notifications.total_count(user_id),
            window=lambda limit, offset: notifications.list_for_user(
                user_id, limit=limit, offset=offset
            ),
        )
        return TemplateResponse(
            request,
            "notifications/index.html",
            {"notifications": list(pagination["page_obj"].object_list), **pagination},
        )


class NotificationOpenActionView(LoginRequiredMixin, View):
    """Mark a notification read, then forward to where it points."""

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        notification = request.services.notifications.mark_read(
            request.context.current_user_id, pk
        )
        if notification is None:
            raise Http404
        # A content notification has nowhere to forward to. With JS the overlay
        # opens in place and this view is never reached; without it, this is
        # where the row gets marked read, so return the reader to the list they
        # clicked from.
        return redirect(
            notification.url
            or safe_url(request, request.META.get("HTTP_REFERER"))
            or reverse("web:notifications")
        )


class NotificationModalComponentView(LoginRequiredMixin, View):
    """Return the overlay dialog for a content notification, marking it read."""

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        notification = request.services.notifications.mark_read(
            request.context.current_user_id, pk
        )
        if notification is None:
            raise Http404
        return TemplateResponse(
            request, "notifications/parts/modal.html", {"notification": notification}
        )
