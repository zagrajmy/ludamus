from typing import TYPE_CHECKING

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString

if TYPE_CHECKING:
    from django.template import Context

register = template.Library()


@register.simple_tag(takes_context=True)
def nonce(context: Context) -> SafeString:
    # Renders ` nonce="…"` (leading space) for `<script{% nonce %}>`.
    # Deliberately `is None`, not a truthy check. Django's LazyNonce is falsy
    # until it is read, and reading it is what generates the value the CSP
    # header ends up carrying. A truthy guard would therefore never read it:
    # no nonce would be generated, the middleware would drop the nonce source
    # from `script-src`, and every inline script on the page would be blocked.
    # `None` means the CSP middleware never ran for this render (a standalone
    # template, or the error path in tests) — there no attribute is correct.
    if (csp_nonce := context.get("csp_nonce")) is None:
        return SafeString("")
    return format_html(' nonce="{}"', csp_nonce)
