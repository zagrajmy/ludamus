"""{% tessera_combobox %} template tag — searchable select."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, TypedDict

from django import template
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from ._registry import register
from ._utils import format_tag_attrs, parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


@dataclass
class _Option:
    disabled: bool
    label: str
    selected: bool
    value: str


class _ComboboxOptions(TypedDict):
    """What the browser is handed in place of the option markup."""

    disabled: bool
    label: str
    rows: list[list[str]]
    value: str


class _OptionReader(HTMLParser):
    """Pulls (value, label, disabled, selected) out of the slot's <option>s.

    The slot is authored as markup, which is what makes the tag pleasant to
    call, but the browser must not have to parse it back: the options ship
    inside a <noscript>, and reading them there would mean turning DOM text
    into HTML again — the shape of an XSS sink, even where the text is our own
    escaped output. Reading them here instead lets the component hand the
    client plain JSON, and this parser only ever sees markup Django rendered.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.options: list[_Option] = []
        self._open: _Option | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "option":
            return
        attributes = dict(attrs)
        self._open = _Option(
            disabled="disabled" in attributes,
            label="",
            selected="selected" in attributes,
            value=attributes.get("value") or "",
        )

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.label += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._open is not None:
            self._open.label = self._open.label.strip()
            self.options.append(self._open)
            self._open = None


def _read_options(slot: str, *, disabled: bool) -> _ComboboxOptions:
    """Turn the slot's options into the data the browser gets, not markup."""
    reader = _OptionReader()
    reader.feed(slot)
    reader.close()
    options = reader.options

    # A single select's value is the option marked selected, or failing that
    # the first one — the browser picks index 0 on its own, and reading the
    # parsed <select> used to give us that for free.
    chosen = next((o for o in options if o.selected), None)
    if chosen is None and options:
        chosen = options[0]

    return {
        "disabled": disabled,
        # The chosen option's label travels on its own, because a disabled one
        # never reaches `rows` and the client looks labels up there. A
        # disabled placeholder ("Choose a fruit…") is the ordinary case: it is
        # what the field shows before anyone picks, and it must not show blank.
        "label": chosen.label if chosen else "",
        # A disabled option is not a row anyone can land on, but it can still
        # be the one showing, so it counts for the value and label above.
        "rows": [[o.value, o.label] for o in options if not o.disabled],
        "value": chosen.value if chosen else "",
    }


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
        # Read, not popped: the hidden input and the <noscript> <select> post
        # under the same name and only one of them ever exists, so both need
        # it. A combobox driving nothing but client-side state has none, which
        # is why this stays optional rather than required.
        name = str(resolved.get("name", ""))
        placeholder = str(resolved.pop("placeholder", "") or _("Search…"))
        empty_text = str(
            resolved.pop("empty_text", "") or _("Nothing matches your search.")
        )
        toggle_label = str(resolved.pop("toggle_label", "") or _("Show options"))
        extra_class = str(resolved.pop("class", ""))
        has_errors = bool(resolved.pop("has_errors", False))
        slot = self.nodelist.render(context)

        return render_to_string(
            self._TEMPLATE,
            {
                "attrs": format_tag_attrs(resolved, boolean_attrs=self._BOOLEAN_ATTRS),
                "empty_text": empty_text,
                "extra_class": extra_class,
                "has_errors": has_errors,
                "id": element_id,
                "name": name,
                "options": _read_options(slot, disabled=bool(resolved.get("disabled"))),
                "options_id": f"{element_id}-options",
                "placeholder": placeholder,
                "slot": slot,
                "toggle_label": toggle_label,
            },
        )


@register.tag("tessera_combobox")
def do_combobox(parser: Parser, token: Token) -> ComboboxNode:
    """Parse ``{% tessera_combobox ... %}...{% end_tessera_combobox %}``.

    Returns:
        A ComboboxNode rendering a select plus the shell that upgrades it.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tessera_combobox",))
    parser.delete_first_token()

    return ComboboxNode(nodelist, attrs)
