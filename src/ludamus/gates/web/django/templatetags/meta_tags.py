from typing import TYPE_CHECKING

from django import template
from django.templatetags.static import static

if TYPE_CHECKING:
    from django.http import HttpRequest

register = template.Library()


@register.simple_tag(takes_context=True)
def meta_image_url(context: template.Context, url: str = "") -> str:
    request: HttpRequest = context["request"]
    return request.build_absolute_uri(url or static("logo.png"))
