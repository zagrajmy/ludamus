from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from ludamus.mills.legacy import render_markdown

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

CONTENT_DIR = Path(__file__).resolve().parents[3] / "content" / "legal"

# Slug to page title. Also the allowlist: it is what stops a future URL entry
# from turning a request into a read of an arbitrary path under CONTENT_DIR.
DOCUMENTS = {
    "privacy-policy": _("Privacy Policy"),
    "terms-of-service": _("Terms of Service"),
}


def legal_document(request: HttpRequest, slug: str) -> HttpResponse:
    if (title := DOCUMENTS.get(slug)) is None:
        raise Http404

    # Read and render per request. These are two rarely-visited pages, and a
    # cache would only buy a millisecond while making an edited file look
    # unchanged until the server restarts.
    source = (CONTENT_DIR / f"{slug}.md").read_text(encoding="utf-8")
    return TemplateResponse(
        request,
        "legal/document.html",
        {"title": title, "content": render_markdown(source)},
    )
