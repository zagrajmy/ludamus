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


# The under-13 answer disables the account and signs it out, and only support
# can undo that, so it takes a second, explicit submit.
_CONFIRM_DISABLE = "disable"


def _page(
    request: AuthenticatedRootRequest,
    *,
    form: AgeRangeForm,
    confirm_disable: bool = False,
) -> TemplateResponse:
    return TemplateResponse(
        request,
        _TEMPLATE,
        {
            "form": form,
            "profile_active_tab": "privacy",
            "confirm_disable": confirm_disable,
        },
    )


class ProfileAgeRangePageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        current = request.services.profile.read(
            request.context.current_user_slug
        ).age_band
        initial = {"age_band": current} if current.is_confirmed else {}
        return _page(request, form=AgeRangeForm(initial=initial))

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        form = AgeRangeForm(request.POST)
        if not form.is_valid():
            return _page(request, form=form)
        user_slug = request.context.current_user_slug
        if (age_band := form.cleaned_data["age_band"]) is None:
            if request.POST.get("confirm") != _CONFIRM_DISABLE:
                return _page(request, form=form, confirm_disable=True)
            request.services.crowd_auth.disable_underage_account(user_slug)
            logger.info("Account disabled: declared below minimum age")
            return sign_out_to_guardian_page(request)
        dropped = request.services.crowd_auth.confirm_age(
            user_slug=user_slug, age_band=age_band
        )
        logger.info("Account age range updated")
        if not dropped:
            message = _("Age range saved. Your bookings are unchanged.")
        elif age_band.allows_optional_features:
            message = _(
                "Age range saved. Your bookings are unchanged. Sphere announcement "
                "subscriptions were cleared; subscribe again from your dashboard."
            )
        else:
            message = _(
                "Age range saved. Your bookings are unchanged. Sphere announcement "
                "subscriptions were cleared."
            )
        messages.success(request, message)
        return redirect("user:profile-privacy")
