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
# The claim and offer tokens are token_urlsafe(48), invariably 64 characters.
# The longest competing segment is a slug: SlugField defaults to 50 and
# mills.slugs caps a base at 45 before a retry suffix, so a convention name
# like `ogolnopolski-konwent-fantastyki-i-gier-bachanalia` has to survive —
# /event/<slug>/ is the most visited page there is. 56 sits between them.
# The party invite token does not reach it: models.Party.invite_token defaults
# to a bare `token_urlsafe`, which is 32 bytes and so 43 characters, below the
# floor and below the longest slug, so no threshold covers both. That route is
# covered by its derived rule alone. It is the one token of the three that is
# not a bearer credential — PartyJoinPageView requires a login, so the token is
# a second factor rather than the whole of one.
# Anchored to a whole segment: a token is always one, while a hashed asset name
# carries an extension and `prologue-DkS9x2Fb.js` must stay readable in both
# analytics and replay.
_FLOOR = Rule(
    re.compile(r"/[A-Za-z0-9_-]{56,}(?=[/?#]|$)"),
    "/:token",
    r"/[A-Za-z0-9_-]{56,}(?=[/?#]|$)",
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
