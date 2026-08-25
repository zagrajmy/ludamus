"""The distinct id and environment tag both halves of the integration send."""

from __future__ import annotations

from django.conf import settings

ANONYMOUS = "anonymous"


def environment() -> str:
    """Which deployment an event came from.

    Staging runs `ENV=production` so it stays production-shaped — CSP, secure
    cookies, log levels — which leaves `IS_STAGING` as the only thing telling
    the two apart.
    """
    return "staging" if settings.IS_STAGING else str(settings.ENV)


def distinct_id(pk: object) -> str:
    """Namespace a user pk so two databases cannot share one PostHog person.

    Every deployment runs the same schema with its own sequence, so a bare pk
    makes staging's user 42 and production's user 42 a single person: their
    events interleave and their properties overwrite each other. Production
    stays unprefixed because its persons already exist under bare pks, and
    renaming them would fork every timeline at the deploy that did it.
    """
    env = environment()
    return str(pk) if env == "production" else f"{env}:{pk}"
