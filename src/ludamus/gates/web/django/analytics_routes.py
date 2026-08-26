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
# Named so the replacement can reference it unambiguously: JS reads `$1` in
# `$10` as group 1 followed by a zero, which a literal starting with a digit
# would trigger.
_SEGMENT = "(?P<p{group}>[^/?#]+)"
_JS_SEGMENT = "(?<p{group}>[^/?#]+)"


def rule_for(route: str) -> redaction.Rule | None:
    """Turn one route template into a substitution, or None if it holds no secret."""
    if not any(
        name in redaction.SECRET_URL_KWARGS for name in _PARAMETER.findall(route)
    ):
        return None

    pattern, js_pattern = ["/"], ["/"]
    python, javascript = ["/"], ["/"]
    position = 0
    for group, match in enumerate(_PARAMETER.finditer(route), start=1):
        literal = route[position : match.start()]
        pattern.append(re.escape(literal))
        js_pattern.append(re.escape(literal))
        # A replacement is not a pattern: each engine has its own escape.
        python.append(literal.replace("\\", "\\\\"))
        javascript.append(literal.replace("$", "$$"))
        name = match.group(1)
        pattern.append(_SEGMENT.format(group=group))
        js_pattern.append(_JS_SEGMENT.format(group=group))
        secret = name in redaction.SECRET_URL_KWARGS
        # Ordinary parameters are kept, so redacting a token does not also cost
        # the event slug sitting beside it in the same route.
        python.append(f":{name}" if secret else f"\\g<p{group}>")
        javascript.append(f":{name}" if secret else f"$<p{group}>")
        position = match.end()
    # Keep the trailing literal, with its final slash optional: a link whose
    # slash a chat client ate still matches, and /offer/list/ no longer looks
    # like a token. Exact rather than a trade.
    if trailing := route[position:].rstrip("/"):
        pattern.append(re.escape(trailing))
        js_pattern.append(re.escape(trailing))
        python.append(trailing.replace("\\", "\\\\"))
        javascript.append(trailing.replace("$", "$$"))
    pattern.append("/?")
    js_pattern.append("/?")
    # Django routes end in a slash, so put it back: a link that lost its slash
    # comes out normalised rather than subtly different from every other event.
    if route.endswith("/"):
        python.append("/")
        javascript.append("/")
    return redaction.Rule(
        re.compile("".join(pattern)),
        "".join(python),
        "".join(js_pattern),
        "".join(javascript),
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
    rules: dict[str, redaction.Rule] = {}
    for route in _routes(get_resolver().url_patterns):
        if rule := rule_for(route):
            rules[rule.pattern.pattern] = rule
    redaction.register(list(rules.values()))
