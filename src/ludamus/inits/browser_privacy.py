from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from django.conf import settings

from ludamus.pacts.crowd import AgeBand

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from django.http import HttpResponseBase

    from ludamus.pacts.services import ServicesProtocol

    class BrowserPrivacyUser(Protocol):
        is_authenticated: bool
        is_active: bool
        age_band: str
        privacy_revision: UUID
        slug: str

    class BrowserPrivacyRequest(Protocol):
        path: str
        method: str
        COOKIES: dict[str, str]
        user: BrowserPrivacyUser
        services: ServicesProtocol


class BrowserPrivacyMiddleware:
    def __init__(
        self, get_response: Callable[[BrowserPrivacyRequest], HttpResponseBase]
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: BrowserPrivacyRequest) -> HttpResponseBase:
        response = self.get_response(request)
        if request.path.startswith(settings.MIDDLEWARE_SKIP_PREFIXES):
            return response
        revision = "off"
        if request.user.is_authenticated:
            user = (
                request.user
                if request.method in {"GET", "HEAD", "OPTIONS"}
                and not AgeBand(request.user.age_band).allows_optional_features
                else request.services.profile.read(request.user.slug)
            )
            if user.is_active and AgeBand(user.age_band).allows_optional_features:
                revision = str(user.privacy_revision)
        if request.COOKIES.get("ludamus.privacy") != revision:
            domain: str | None = settings.SESSION_COOKIE_DOMAIN
            root_domain: str = settings.ROOT_DOMAIN
            response.set_cookie(
                "ludamus.privacy",
                revision,
                domain=domain or urlsplit(f"//{root_domain}").hostname,
                path="/",
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=False,
                samesite="Lax",
            )
        return response
