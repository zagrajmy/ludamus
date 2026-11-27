from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404
from django.template.response import TemplateResponse
from django.views.decorators.csp import csp_override

from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.external_tools import ExternalToolDTO


def tool_page(request: RootRequest, slug: str) -> HttpResponse:
    try:
        tool = request.services.external_tools.read_active(slug)
    except NotFoundError as error:
        raise Http404 from error

    response = TemplateResponse(request, "tools/page.html", {"tool": tool})
    # Absent or disabled, the policy restricts no frame: leave it that way.
    if not (policy := settings.SECURE_CSP):
        return response
    config = {**policy, "frame-src": _frame_sources(tool)}
    return csp_override(config)(lambda _request: response)(request)


def _frame_sources(tool: ExternalToolDTO) -> list[str]:
    # netloc, not hostname: a source without the port matches only port 443.
    hosts = (urlsplit(tool.url).netloc, *tool.allowed_domains)
    return [f"https://{host}" for host in hosts]
