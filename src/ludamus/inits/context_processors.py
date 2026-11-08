"""Template context that needs a link: the analytics client configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypedDict

from django.conf import settings

from ludamus.links.analytics import identity, redaction
from ludamus.pacts.user import AgeBand

if TYPE_CHECKING:
    from uuid import UUID

    class AnalyticsUser(Protocol):
        is_authenticated: bool
        pk: int
        age_band: str
        privacy_revision: UUID

    class AnalyticsRequest(Protocol):
        user: AnalyticsUser


class PosthogConfig(TypedDict):
    api_key: str
    environment: str
    host: str
    # Derived from the URLconf so the browser redacts the same segments the
    # server does, rather than keeping its own copy of the route list.
    redaction_rules: list[list[str]]
    user_id: str
    privacy_revision: str


class AnalyticsContextData(TypedDict):
    posthog_config: PosthogConfig | None


def analytics(request: AnalyticsRequest) -> AnalyticsContextData:
    api_key: str = settings.POSTHOG_API_KEY
    host: str = settings.POSTHOG_HOST
    # The error handlers render before the authentication middleware has run.
    if not api_key or not hasattr(request, "user"):
        return AnalyticsContextData(posthog_config=None)
    user = request.user
    if not user.is_authenticated or not AgeBand(user.age_band).allows_optional_features:
        return AnalyticsContextData(posthog_config=None)
    # Identify by pk, not slug: a slug follows a rename and would split one
    # person across two distinct_ids. request.user rather than the profile
    # service — the auth middleware already resolved it, so this costs no
    # extra query. distinct_id namespaces it per deployment so staging and
    # production cannot land on the same person.
    return AnalyticsContextData(
        posthog_config=PosthogConfig(
            api_key=api_key,
            host=host,
            user_id=identity.distinct_id(user.pk),
            privacy_revision=str(user.privacy_revision),
            environment=identity.environment(),
            redaction_rules=redaction.client_patterns(),
        )
    )
