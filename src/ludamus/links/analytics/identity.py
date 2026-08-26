"""What both halves of the integration may send, and under what name.

Every rule here has a twin in `client/src/prologue.ts`: the browser and the
server report into one project, so they have to agree on how a person is
named, which deployment an event came from, and what a path may reveal.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import Resolver404, resolve


def environment() -> str:
    """Which deployment an event came from.

    Staging runs `ENV=production` so it stays production-shaped — CSP, secure
    cookies, log levels — which leaves `IS_STAGING` as the only thing telling
    the two apart.
    """
    return "staging" if settings.IS_STAGING else str(settings.ENV)


def distinct_id(pk: int) -> str:
    """Namespace a user pk so two databases cannot share one PostHog person.

    Every deployment runs the same schema with its own sequence, so a bare pk
    makes staging's user 42 and production's user 42 a single person: their
    events interleave and their properties overwrite each other. Separate
    projects would sidestep this; one shared project is the choice we made,
    and this is what that choice costs.

    Production keeps the bare pk so the persons it already has stay one
    person across the deploy that adds this.
    """
    env = environment()
    return str(pk) if env == "production" else f"{env}:{pk}"


# A path segment can be a credential: the claim, party-invite and session-offer
# links all authenticate by bearing a token, which is what lets those flows work
# without a login. Rather than enumerate those routes here and have the list rot
# — it already missed /offer/ once — ask the URLconf which segments are
# parameters and blank the ones named after a secret.
_SECRET_URL_KWARGS = frozenset({"token", "share_code"})


def safe_path(path: str) -> str:
    """Replace any secret-bearing URL segment with its parameter name."""
    try:
        match = resolve(path)
    except Resolver404:
        return path
    for name, value in match.kwargs.items():
        if name in _SECRET_URL_KWARGS and isinstance(value, str) and value:
            path = path.replace(value, f":{name}")
    return path
