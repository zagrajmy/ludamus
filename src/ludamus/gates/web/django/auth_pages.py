from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from django.template.response import TemplateResponse

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest

logger = logging.getLogger(__name__)

# Auth0 tracking ids are short hex tokens; anything else on this
# attacker-suppliable param is dropped rather than rendered.
_TRACKING_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


def login_required_page(request: RootRequest) -> TemplateResponse:
    context = {
        "next": request.GET.get("next", ""),
        # Inputs of the login_button.html component.
        "show_icon": True,
        "text": "",
        "extra_class": "",
    }
    return TemplateResponse(request, "crowd/login_required.html", context)


def auth_error_page(request: RootRequest) -> TemplateResponse:
    tracking = request.GET.get("tracking", "")
    if not _TRACKING_RE.fullmatch(tracking):
        tracking = ""
    logger.warning(
        "Auth0 error redirect: error=%s tracking=%s",
        request.GET.get("error", "")[:64],
        tracking or "-",
    )
    return TemplateResponse(request, "crowd/auth_error.html", {"tracking": tracking})
