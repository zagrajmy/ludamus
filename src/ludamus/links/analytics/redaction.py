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

import re
from typing import NamedTuple

SECRET_URL_KWARGS = frozenset({"token"})


class Rule(NamedTuple):
    """One substitution, in each engine's own dialect.

    Python and ECMAScript spell a named group differently — `(?P<p1>…)` versus
    `(?<p1>…)` — and a JavaScript RegExp raises on Python's form, which would
    take down `posthog.init` and with it every event on the page. Both sides are
    built from the route rather than derived from one another.
    """

    pattern: re.Pattern[str]
    python: str
    javascript_pattern: str
    javascript: str


# Always applied, before anything gates registers. It makes redaction
# independent of startup order, of the kwarg still being spelled `token`, and
# of the route being a path() rather than a re_path() the walk skips.
# secrets.token_urlsafe(48) is 64 characters; the longest legitimate segment in
# this app is a six-character share code, so the floor cannot swallow one.
# Anchored to a whole segment: a token is always one, while a hashed asset name
# carries an extension, and `prologue-DkS9x2Fb.js` must stay readable in both
# analytics and replay.
_FLOOR = Rule(
    re.compile(r"/[A-Za-z0-9_-]{40,}(?=[/?#]|$)"),
    "/:token",
    r"/[A-Za-z0-9_-]{40,}(?=[/?#]|$)",
    "/:token",
)

# Mutated rather than rebound so nothing has to reach for `global`, and so a
# module that imported the list still sees what gates registered.
_rules: list[Rule] = []


def register(rules: list[Rule]) -> None:
    """Install the rules derived from the URLconf. Called once, at startup."""
    _rules.clear()
    _rules.extend(rules)


def safe_path(path: str) -> str:
    """Replace every secret-bearing segment with its parameter name.

    Matched by prefix rather than resolved, so a link whose trailing slash a
    chat client swallowed is still redacted. Resolving it would raise, and
    returning that path unchanged would ship the whole token.
    """
    for rule in (*_rules, _FLOOR):
        path = rule.pattern.sub(rule.python, path)
    return path


def client_patterns() -> list[list[str]]:
    """Serialise the rules as `[source, replacement]` pairs the browser compiles."""
    return [[rule.javascript_pattern, rule.javascript] for rule in (*_rules, _FLOOR)]
