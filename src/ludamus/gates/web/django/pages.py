from __future__ import annotations

from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

CONTENT_DIR = Path(__file__).resolve().parents[3] / "content"

# Slug to page title, and the allowlist that keeps a request from becoming a
# read of an arbitrary path under CONTENT_DIR. Every key needs a matching
# {slug}.md beside it, which may name `$staff_email` for the contact address.
PAGES = {
    "privacy-policy": _("Privacy Policy"),
    "terms-of-service": _("Terms of Service"),
}


def read_document(slug: str) -> str:
    text = (CONTENT_DIR / f"{slug}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(staff_email=settings.STAFF_EMAIL)


def content_page(request: HttpRequest, slug: str) -> HttpResponse:
    if (title := PAGES.get(slug)) is None:
        raise Http404

    # Read per request. These are a handful of rarely-visited pages, and a cache
    # would only buy a millisecond while making an edited file look unchanged
    # until the server restarts. The template renders the markdown, through the
    # same filter every other prose surface uses.
    return TemplateResponse(
        request, "content/page.html", {"title": title, "document": read_document(slug)}
    )
