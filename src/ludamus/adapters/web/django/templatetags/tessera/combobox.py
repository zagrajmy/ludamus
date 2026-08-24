"""{% tessera_combobox %} template tag — searchable select."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from ._registry import register
from ._utils import format_tag_attrs, parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


class ComboboxNode(template.Node):
    """Renders a ``<select>`` the browser upgrades into an APG combobox."""

    _BOOLEAN_ATTRS = ("required", "disabled")
    _TEMPLATE = "components/combobox.html"

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }

        # Copy the combobox owns, and `class`/`has_errors` as on {% select %};
        # every other keyword is forwarded onto the <select> element.
        element_id = str(resolved.get("id", ""))
        placeholder = str(resolved.pop("placeholder", "") or _("Search…"))
        empty_text = str(
            resolved.pop("empty_text", "") or _("Nothing matches your search.")
        )
        toggle_label = str(resolved.pop("toggle_label", "") or _("Show options"))
        extra_class = str(resolved.pop("class", ""))
        has_errors = bool(resolved.pop("has_errors", False))

        return render_to_string(
            self._TEMPLATE,
            {
                "attrs": format_tag_attrs(resolved, boolean_attrs=self._BOOLEAN_ATTRS),
                "empty_text": empty_text,
                "extra_class": extra_class,
                "has_errors": has_errors,
                "id": element_id,
                "placeholder": placeholder,
                "slot": self.nodelist.render(context),
                "toggle_label": toggle_label,
            },
        )


@register.tag("tessera_combobox")
def do_combobox(parser: Parser, token: Token) -> ComboboxNode:
    """Parse ``{% tessera_combobox ... %}...{% endtessera_combobox %}``.

    Returns:
        A ComboboxNode rendering a select plus the shell that upgrades it.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("endtessera_combobox",))
    parser.delete_first_token()

    return ComboboxNode(nodelist, attrs)
