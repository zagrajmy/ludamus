"""Shared utilities for tessera template tag parsers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.html import format_html, format_html_join

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.template.base import FilterExpression, Parser, Token


def parse_tag_attrs(parser: Parser, token: Token) -> dict[str, FilterExpression]:
    """Parse ``key=value`` pairs from a template tag token.

    Returns:
        Dict mapping attribute names to compiled filter expressions.
    """
    attrs: dict[str, FilterExpression] = {}
    for bit in token.split_contents()[1:]:
        key, _, value = bit.partition("=")
        attrs[key] = parser.compile_filter(value)
    return attrs


def format_tag_attrs(
    resolved: Mapping[str, object], *, boolean_attrs: tuple[str, ...] = ()
) -> str:
    """Render resolved tag keywords as one HTML attribute string.

    Returns:
        Attributes joined by spaces, each already escaped.
    """
    parts: list[str] = []
    for key, value in resolved.items():
        if key in boolean_attrs:
            if value:
                parts.append(format_html("{}", key))
            continue
        # `value=0` is a legitimate radio value — only drop absent attrs.
        if value is None or (isinstance(value, str) and not value):
            continue
        # Template kwargs can't contain hyphens, so aria_*/data_* keywords
        # map onto their hyphenated attributes (aria_label -> aria-label).
        name = key.replace("_", "-") if key.startswith(("aria_", "data_")) else key
        parts.append(format_html('{}="{}"', name, value))
    return format_html_join(" ", "{}", ((part,) for part in parts))
