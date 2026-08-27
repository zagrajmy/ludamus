"""How both halves of the integration name a person and their deployment."""

from __future__ import annotations

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
