"""Which URL segments may never reach the analytics project.

Claim links, session offers and ticket orders authenticate by bearing a token
in the path — that is what lets those flows work without a login — so such a
path is a credential, not a location.

The rules are not written here. `gates` derives them from the URLconf, which is
the only place that knows which segments are parameters, and `inits` hands that
derivation over at startup; this module only applies them. Both halves of the
integration consume that one list: the server through `safe_path`, the browser
through `client_patterns`, which the context processor ships in the page. One
derivation, two consumers, so neither half can drift from the routes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ludamus.pacts.analytics import RedactionRule

if TYPE_CHECKING:
    from collections.abc import Callable

# Always applied, even before the derived rules arrive. It makes redaction
# independent of startup order, of the kwarg still being spelled `token`, and
# of the route being a path() rather than a re_path() the walk skips.
# The claim and offer tokens are token_urlsafe(48), invariably 64 characters.
# The longest competing segment is a slug: SlugField defaults to 50 and
# pacts.slugs caps a base at 45 before a retry suffix, so a convention name
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
# analytics and replay. Lower-case hex is excluded for the same reason — a
# gravatar URL ends in a sha256 digest, also 64 characters, and a token is
# base64url so it carries upper case or -_ that a digest never can.
_FLOOR = RedactionRule(
    re.compile(r"/(?![0-9a-f]{56,}(?=[/?#]|$))[A-Za-z0-9_-]{56,}(?=[/?#]|$)"),
    "/:token",
    r"/(?![0-9a-f]{56,}(?=[/?#]|$))[A-Za-z0-9_-]{56,}(?=[/?#]|$)",
    "/:token",
)


class _Rules:
    """What gates derives, built on first use rather than at startup.

    Deriving the rules means walking the URLconf, which imports every view. Held
    behind a callable, that cost lands on the first event instead of on every
    `manage.py` invocation, and the rules cannot go stale against a URLconf that
    changed after AppConfig.ready() ran.
    """

    def __init__(self) -> None:
        self._build: Callable[[], list[RedactionRule]] | None = None
        self._cache: list[RedactionRule] | None = None

    def set_builder(self, build: Callable[[], list[RedactionRule]]) -> None:
        self._build = build
        self._cache = None

    def set(self, rules: list[RedactionRule]) -> None:
        self._build = None
        self._cache = list(rules)

    def get(self) -> list[RedactionRule]:
        if self._cache is None:
            self._cache = list(self._build()) if self._build else []
        return self._cache


_rules = _Rules()


def register_builder(build: Callable[[], list[RedactionRule]]) -> None:
    """Hand over how to derive the rules. Called once, at startup."""
    _rules.set_builder(build)


def register(rules: list[RedactionRule]) -> None:
    """Install rules directly, bypassing the builder. For tests."""
    _rules.set(rules)


def safe_path(path: str) -> str:
    """Replace every secret-bearing segment with its parameter name.

    Matched by prefix rather than resolved, so a link whose trailing slash a
    chat client swallowed is still redacted. Resolving it would raise, and
    returning that path unchanged would ship the whole token.
    """
    for rule in (*_rules.get(), _FLOOR):
        path = rule.pattern.sub(rule.python, path)
    return path


def client_patterns() -> list[list[str]]:
    """Serialise the rules as `[source, replacement]` pairs the browser compiles."""
    return [
        [rule.javascript_pattern, rule.javascript] for rule in (*_rules.get(), _FLOOR)
    ]
