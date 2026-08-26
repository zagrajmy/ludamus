"""What both halves of the integration may send, and under what name.

Every rule here has a twin in `client/src/prologue.ts`: the browser and the
server report into one project, so they have to agree on how a person is
named, which deployment an event came from, and what a path may reveal.
"""

from __future__ import annotations

import re

from django.conf import settings


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


# Claim links and party invites authenticate by bearing the token in the path —
# that is what lets those flows work without a login — so a path holding one is
# a credential, not a location, and must not reach the project.
_TOKEN_PATHS = re.compile(r"/crowd/(claim|parties/join)/[^/]+")


def safe_path(path: str) -> str:
    """Strip bearer tokens out of a path before it becomes an event property."""
    return _TOKEN_PATHS.sub(r"/crowd/\1/:token", path)
