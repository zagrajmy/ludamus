"""Derive the analytics redaction rules from the URLconf.

The URLconf is the only place that knows which path segments are parameters,
and it lives here. `links.analytics.redaction` applies what this registers, so
a route added with a `token` parameter is covered without anyone remembering to
update a second list — the previous hand-kept one had already missed /offer/.
"""

from __future__ import annotations

import re

from django.urls import URLPattern, URLResolver, get_resolver

from ludamus.links.analytics import redaction

# `<int:pk>`, `<slug:slug>`, `<token>` — the converter is optional.
_PARAMETER = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
# A parameter never spans a slash, and stops at a query string or fragment.
_SEGMENT = "([^/?#]+)"


def _rule_for(route: str) -> tuple[re.Pattern[str], str] | None:
    """Turn one route template into a substitution, or None if it holds no secret."""
    if not any(
        name in redaction.SECRET_URL_KWARGS for name in _PARAMETER.findall(route)
    ):
        return None

    pattern, replacement = ["/"], ["/"]
    position = 0
    for group, match in enumerate(_PARAMETER.finditer(route), start=1):
        literal = route[position : match.start()]
        pattern.append(re.escape(literal))
        replacement.append(literal.replace("\\", "\\\\"))
        name = match.group(1)
        pattern.append(_SEGMENT)
        # Keep the ordinary parameters, so redacting a token does not also cost
        # us the event slug sitting next to it in the same route.
        replacement.append(
            f":{name}" if name in redaction.SECRET_URL_KWARGS else f"\\{group}"
        )
        position = match.end()
    # The trailing literal is dropped on purpose: it anchors nothing, and
    # leaving it off means a link with its final slash eaten still matches.
    return re.compile("".join(pattern)), "".join(replacement)


def _routes(patterns: object, prefix: str = "") -> list[str]:
    resolved: list[str] = []
    for entry in patterns:  # type: ignore[attr-defined]
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            resolved.extend(_routes(entry.url_patterns, route))
        elif isinstance(entry, URLPattern):
            resolved.append(route)
    return resolved


def register_redaction_rules() -> None:
    """Walk the URLconf once and hand the secret-bearing routes to links."""
    # Routes sharing a prefix collapse to one rule once the trailing literal is
    # dropped — /offer/<token>/claim and /decline are the same substitution.
    rules: dict[str, tuple[re.Pattern[str], str]] = {}
    for route in _routes(get_resolver().url_patterns):
        if rule := _rule_for(route):
            rules[rule[0].pattern] = rule
    redaction.register(list(rules.values()))
