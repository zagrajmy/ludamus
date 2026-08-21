from typing import TYPE_CHECKING

from django import template
from django.templatetags.static import static
from django.utils.safestring import SafeString

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.template.base import Parser, Token

register = template.Library()


@register.simple_tag(takes_context=True)
def meta_image_url(context: template.Context, url: str = "") -> str:
    request: HttpRequest = context["request"]
    return request.build_absolute_uri(url or static("logo.png"))


class DocumentTitleNode(template.Node):
    def __init__(self, nodelist: template.NodeList) -> None:
        self.nodelist = nodelist

    # The title is one value in three tags (<title>, og:title, twitter:title)
    # and a block can't hand its output to a variable, so capture it here. The
    # inner nodes escape their own output; collapsing whitespace only drops the
    # newlines the template's indentation left behind, so the result stays safe.
    # The name lands in the context the tag was reached with, so the tag belongs
    # at the top level of the page shell, ahead of every {{ document_title }}
    # that reads it. Nested inside a block it would be popped with that block.
    def render(self, context: template.Context) -> str:
        rendered = self.nodelist.render(context)
        context["document_title"] = SafeString(" ".join(rendered.split()))
        return ""


@register.tag("document_title")
def document_title(parser: Parser, _token: Token) -> DocumentTitleNode:
    nodelist = parser.parse(("end_document_title",))
    parser.delete_first_token()
    return DocumentTitleNode(nodelist)
