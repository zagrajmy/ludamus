from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.crowd.auth import sign_out_to_guardian_page
from ludamus.gates.web.django.crowd.forms import AgeRangeForm

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest

logger = logging.getLogger(__name__)

_TEMPLATE = "crowd/user/age_range.html"


class ProfileAgeRangePageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        return TemplateResponse(
            request,
            _TEMPLATE,
            {"form": AgeRangeForm(), "profile_active_tab": "privacy"},
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        form = AgeRangeForm(request.POST)
        if not form.is_valid():
            return TemplateResponse(
                request, _TEMPLATE, {"form": form, "profile_active_tab": "privacy"}
            )
        user_slug = request.context.current_user_slug
        if (age_band := form.cleaned_data["age_band"]) is None:
            request.services.crowd_auth.disable_underage_account(user_slug)
            logger.info("Account disabled: declared below minimum age")
            return sign_out_to_guardian_page(request)
        request.services.crowd_auth.confirm_age(user_slug=user_slug, age_band=age_band)
        logger.info("Account age range updated")
        messages.success(request, _("Age range saved. Your bookings are unchanged."))
        return redirect("user:profile-privacy")
