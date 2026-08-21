from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.template.response import TemplateResponse

from ludamus.pacts.legacy import SpherePage

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


def index_page(request: RootRequest) -> HttpResponse:
    context = request.context
    if context.current_sphere_id == context.root_sphere_id:
        stats = request.services.landing.stats()
        return TemplateResponse(request, ["landing_page.html"], {"stats": stats})
    sphere = request.services.sites.read(context.current_sphere_id)
    if sphere.default_page == SpherePage.ENCOUNTERS:
        return redirect("web:notice-board:index")
    return redirect("web:events")
