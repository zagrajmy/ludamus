"""WeasyPrint boundary for rendering Django templates to PDF bytes."""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from weasyprint import HTML


def render_template_to_pdf(
    template_name: str, context: dict[str, Any], *, base_url: str
) -> bytes:
    html = render_to_string(template_name, context)
    pdf_bytes: bytes = HTML(string=html, base_url=base_url).write_pdf()
    return pdf_bytes
