from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from django.template.response import TemplateResponse

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest

logger = logging.getLogger(__name__)

# Auth0 sends short machine tokens on both params (tracking ids like
# d9bd4fc6d133caf8b064, error codes like invalid_request); anything else on
# these attacker-suppliable params is dropped rather than rendered or logged.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _vetted_token(request: RootRequest, param: str) -> str:
    value = request.GET.get(param, "")
    return value if _TOKEN_RE.fullmatch(value) else ""


def login_required_page(request: RootRequest) -> TemplateResponse:
    context = {"next": request.GET.get("next", "")}
    return TemplateResponse(request, "crowd/login_required.html", context)


def auth_error_page(request: RootRequest) -> TemplateResponse:
    tracking = _vetted_token(request, "tracking")
    error_code = _vetted_token(request, "error")
    if "tracking" in request.GET or "error" in request.GET:
        logger.warning(
            "Auth0 error redirect: error=%s tracking=%s",
            error_code or "-",
            tracking or "-",
        )
    return TemplateResponse(request, "crowd/auth_error.html", {"tracking": tracking})
