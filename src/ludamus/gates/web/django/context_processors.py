from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.entities import UserInfo

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.notifications import NavbarNotificationsDTO
    from ludamus.pacts.sphere import SiteDTO, SphereDTO
    from ludamus.pacts.user import UserDTO


class SitesContextData(TypedDict):
    root_origin: str
    current_site: SiteDTO | None
    current_sphere: SphereDTO | None
    is_root_sphere: bool
    has_panel_access: bool


def sites(request: RootRequest) -> SitesContextData:
    # Context processor may run during error handling before middleware completes
    if not hasattr(request, "context") or not hasattr(
        request, "services"
    ):  # pragma: no cover
        return SitesContextData(
            root_origin="",
            current_site=None,
            current_sphere=None,
            is_root_sphere=True,
            has_panel_access=False,
        )

    sites_service = request.services.sites
    root_sphere = sites_service.read(request.context.root_sphere_id)
    is_root_sphere = request.context.current_sphere_id == request.context.root_sphere_id
    current_sphere = (
        root_sphere
        if is_root_sphere
        else sites_service.read(request.context.current_sphere_id)
    )

    return SitesContextData(
        root_origin=f"{request.scheme}://{root_sphere.site.domain}",
        current_site=current_sphere.site,
        current_sphere=current_sphere,
        is_root_sphere=is_root_sphere,
        has_panel_access=has_panel_access(request),
    )


def support(_request: HttpRequest) -> dict[str, str]:
    return {"SUPPORT_EMAIL": settings.SUPPORT_EMAIL}


def board(_request: HttpRequest) -> dict[str, bool]:
    return {"BOARD_PUBLIC": settings.BOARD_PUBLIC}


def parley(request: RootRequest) -> dict[str, SimpleLazyObject[bool]]:
    # Only where the chat can sign passes and reach a Worker; elsewhere its
    # button could never connect. Asked only of a page that shows it.
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    user_id = getattr(getattr(request, "context", None), "current_user_id", None)
    configured = bool(agent_host and private_key)
    return {
        "PARLEY_OPEN": SimpleLazyObject(
            lambda: (
                configured
                and user_id is not None
                and request.services.parley.is_open_to(
                    user_id=user_id, now=datetime.now(tz=UTC)
                )
            )
        )
    }


def static_version(_request: HttpRequest) -> dict[str, str]:
    return {
        "COMMIT_SHA": settings.COMMIT_SHA,
        "STATIC_VERSION": settings.STATIC_VERSION,
    }


class CurrentUserContextData(TypedDict):
    optional_features_available: bool
    current_user_info: NotRequired[UserInfo]
    current_user: UserDTO | None
    navbar_notifications: NotRequired[NavbarNotificationsDTO]


def current_user(request: RootRequest) -> CurrentUserContextData:
    # Context processor may run during error handling before middleware completes
    if (
        not hasattr(request, "context")
        or not hasattr(request, "services")
        or not request.context.current_user_slug
    ):
        return CurrentUserContextData(
            current_user=None, optional_features_available=False
        )

    user_dto = request.services.profile.read(request.context.current_user_slug)
    return CurrentUserContextData(
        current_user=user_dto,
        optional_features_available=user_dto.age_band.allows_optional_features,
        current_user_info=UserInfo.from_user_dto(user_dto),
        navbar_notifications=request.services.notifications.get_navbar(user_dto.pk),
    )


class BrandingContextData(TypedDict):
    favicon: str


def branding(_request: HttpRequest) -> BrandingContextData:
    # Each SVG adapts to dark tab bars via its own prefers-color-scheme rule
    # (dev is a solid teal mark that reads on either tab bar as-is).
    if settings.IS_STAGING:
        return BrandingContextData(favicon="favicon-staging.svg")
    if settings.IS_PRODUCTION:
        return BrandingContextData(favicon="favicon.svg")
    return BrandingContextData(favicon="favicon-dev.svg")
