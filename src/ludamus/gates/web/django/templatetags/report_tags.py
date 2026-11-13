from typing import TYPE_CHECKING

from django import template
from django.urls import reverse
from django.utils.http import urlencode

if TYPE_CHECKING:
    from django.http import HttpRequest

register = template.Library()


@register.simple_tag(takes_context=True)
def report_url(context: template.Context, path: str = "", **query: str | int) -> str:
    """Link the notice form with what to report filled in: this page, or `path`.

    The page goes in without its query string, which may carry a token.
    """
    request: HttpRequest = context["request"]
    target = request.build_absolute_uri(path or request.path)
    if query:
        target = f"{target}?{urlencode(query)}"
    return f"{reverse('report')}?{urlencode({'url': target})}"
