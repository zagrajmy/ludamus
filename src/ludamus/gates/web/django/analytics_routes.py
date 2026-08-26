"""Derive the analytics redaction rules from the URLconf.

The URLconf is the only place that knows which path segments are parameters,
and it lives here. `links.analytics.redaction` applies what this registers, so
a route added with a `token` parameter is covered without anyone updating a
second list — the hand-kept one had already missed /offer/.
"""

from __future__ import annotations

import re

from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RoutePattern

from ludamus.links.analytics import redaction

# `<int:pk>`, `<slug:slug>`, `<token>` — the converter is optional.
_PARAMETER = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
# A parameter never spans a slash, and stops at a query string or fragment.
_SEGMENT = "([^/?#]+)"
# Escaped by hand rather than with re.escape: that escapes `-`, `#`, `&` and
# `~` too, which Python accepts and ECMAScript rejects under /u. These are the
# characters both engines agree are metacharacters. `/` is not among them: the
# patterns are built with new RegExp(), not literal notation.
_METACHARACTERS = frozenset("^$\\.*+?()[]{}|")


def _escape(literal: str) -> str:
    return "".join(f"\\{char}" if char in _METACHARACTERS else char for char in literal)


def rule_for(route: str) -> redaction.Rule | None:
    """Turn one route template into a substitution, or None if it holds no secret."""
    if not any(
        name in redaction.SECRET_URL_KWARGS for name in _PARAMETER.findall(route)
    ):
        return None

    pattern, python, javascript = ["/"], ["/"], ["/"]
    position = 0
    for group, match in enumerate(_PARAMETER.finditer(route), start=1):
        literal = route[position : match.start()]
        pattern.append(_escape(literal))
        # A replacement is not a pattern: each engine has its own escape.
        python.append(literal.replace("\\", "\\\\"))
        javascript.append(literal.replace("$", "$$"))
        name = match.group(1)
        pattern.append(_SEGMENT)
        secret = name in redaction.SECRET_URL_KWARGS
        # Ordinary parameters are kept, so redacting a token does not also cost
        # the event slug sitting beside it in the same route.
        python.append(f":{name}" if secret else f"\\g<{group}>")
        javascript.append(f":{name}" if secret else f"${group}")
        position = match.end()
    # The trailing literal is dropped on purpose. It anchors nothing, and
    # leaving it off means a link whose final slash a chat client ate still
    # matches. The cost is over-matching a sibling like /offer/list/, which is
    # the right way to be wrong.
    return redaction.Rule(
        re.compile("".join(pattern)), "".join(python), "".join(javascript)
    )


def _routes(patterns: list[URLPattern | URLResolver], prefix: str = "") -> list[str]:
    resolved: list[str] = []
    for entry in patterns:
        # re_path entries carry a regex, not a route template, and _PARAMETER
        # would happily match a (?P<token>…) group inside one and emit a
        # pattern that silently never matches. Only routes are translatable.
        if not isinstance(entry.pattern, RoutePattern):
            continue
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
    rules: dict[str, redaction.Rule] = {}
    for route in _routes(get_resolver().url_patterns):
        if rule := rule_for(route):
            rules[rule.pattern.pattern] = rule
    redaction.register(list(rules.values()))
