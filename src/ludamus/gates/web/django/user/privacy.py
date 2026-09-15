from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.template.response import TemplateResponse
from django.views.generic.base import View

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


class ProfilePrivacyPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        return TemplateResponse(
            request, "crowd/user/privacy.html", {"profile_active_tab": "privacy"}
        )
