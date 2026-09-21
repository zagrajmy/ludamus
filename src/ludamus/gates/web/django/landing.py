from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.template.response import TemplateResponse

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


def index_page(request: RootRequest) -> HttpResponse:
    # The root sphere gets the marketing landing page; every other sphere's
    # single feed lives at /events (the old per-sphere default_page choice
    # was folded away there).
    context = request.context
    if context.current_sphere_id == context.root_sphere_id:
        landing = request.services.landing
        return TemplateResponse(
            request,
            ["landing_page.html"],
            {"stats": landing.stats(), "conventions": landing.conventions()},
        )
    return redirect("web:events")
