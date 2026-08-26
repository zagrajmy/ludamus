"""Which URL segments may never reach the analytics project.

Claim links and session offers authenticate by bearing a token in the path —
that is what lets those flows work without a login — so such a path is a
credential, not a location.

The rules are not written here. `gates` derives them from the URLconf, which is
the only place that knows which segments are parameters, and registers them at
startup; this module only applies them. Both halves of the integration consume
that one list: the server through `safe_path`, the browser through
`client_patterns`, which the context processor ships in the page. One
derivation, two consumers, so neither half can drift from the routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re

SECRET_URL_KWARGS = frozenset({"token"})

# Mutated rather than rebound so nothing has to reach for `global`, and so a
# module that imported the list still sees what gates registered.
_rules: list[tuple[re.Pattern[str], str]] = []


def register(rules: list[tuple[re.Pattern[str], str]]) -> None:
    """Install the rules derived from the URLconf. Called once, at startup."""
    _rules.clear()
    _rules.extend(rules)


def safe_path(path: str) -> str:
    """Replace every secret-bearing segment with its parameter name.

    Pattern-based rather than resolver-based so that it fails closed: a link
    whose trailing slash a chat client swallowed resolves to nothing, and
    returning such a path unchanged would ship the whole token.
    """
    for pattern, replacement in _rules:
        path = pattern.sub(replacement, path)
    return path


def client_patterns() -> list[list[str]]:
    """Serialise the rules as `[source, replacement]` pairs the browser compiles."""
    return [
        [pattern.pattern, replacement.replace("\\", "$")]
        for pattern, replacement in _rules
    ]
