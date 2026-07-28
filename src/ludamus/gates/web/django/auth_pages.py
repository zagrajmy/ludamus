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
_TRACKING_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
_ERROR_CODE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def login_required_page(request: RootRequest) -> TemplateResponse:
    context = {"next": request.GET.get("next", "")}
    return TemplateResponse(request, "crowd/login_required.html", context)


def auth_error_page(request: RootRequest) -> TemplateResponse:
    tracking = request.GET.get("tracking", "")
    if not _TRACKING_RE.fullmatch(tracking):
        tracking = ""
    error_code = request.GET.get("error", "")
    if not _ERROR_CODE_RE.fullmatch(error_code):
        error_code = ""
    logger.warning(
        "Auth0 error redirect: error=%s tracking=%s", error_code or "-", tracking or "-"
    )
    return TemplateResponse(request, "crowd/auth_error.html", {"tracking": tracking})
