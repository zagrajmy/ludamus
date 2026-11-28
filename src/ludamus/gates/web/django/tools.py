from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.http import Http404
from django.template.response import TemplateResponse

from ludamus.gates.web.django.helpers import respond_with_policy
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


def tool_page(request: RootRequest, slug: str) -> HttpResponse:
    try:
        tool = request.services.external_tools.read_active(slug)
    except NotFoundError as error:
        raise Http404 from error

    response = TemplateResponse(request, "tools/page.html", {"tool": tool})
    # Absent or disabled, the policy restricts no frame: leave it that way.
    if not (policy := settings.SECURE_CSP):
        return response
    frame_src = [f"https://{host}" for host in tool.frame_hosts]
    return respond_with_policy(request, response, {**policy, "frame-src": frame_src})
