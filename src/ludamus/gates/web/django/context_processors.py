from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from django.conf import settings
from django.urls import reverse

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.sphere.pages import (
    SPHERE_PAGE_LABELS,
    SPHERE_PAGE_NAMESPACES,
    SPHERE_PAGE_URL_NAMES,
)
from ludamus.links.analytics import identity, redaction
from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.adapters.web.django.middlewares import RootRepositoryRequest
    from ludamus.pacts import SiteDTO, SphereDTO
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.enrollment import NavbarNotificationsDTO


class SpherePageNavItem(TypedDict):
    label: str
    url: str
    is_active: bool


class SitesContextData(TypedDict):
    root_site: SiteDTO | None
    current_site: SiteDTO | None
    current_sphere: SphereDTO | None
    is_root_sphere: bool
    has_panel_access: bool
    sphere_page_nav: list[SpherePageNavItem]


def _active_sphere_page(request: HttpRequest) -> SpherePage | None:
    """Name the page group the current URL belongs to, if any."""
    if (match := request.resolver_match) is None:
        return None
    for namespace in match.namespaces:
        if page := SPHERE_PAGE_NAMESPACES.get(namespace):
            return page
    # The two group landing pages carry no namespace of their own.
    return {"events": SpherePage.EVENTS, "timeline": SpherePage.TIMELINE}.get(
        match.url_name or ""
    )


def _sphere_page_nav(
    request: HttpRequest, sphere: SphereDTO | None
) -> list[SpherePageNavItem]:
    if sphere is None:
        return []
    active = _active_sphere_page(request)
    return [
        SpherePageNavItem(
            label=str(SPHERE_PAGE_LABELS[page]),
            url=reverse(SPHERE_PAGE_URL_NAMES[page]),
            is_active=page is active,
        )
        # Ordered by the enum, not by the sphere's list, so the navbar reads
        # the same everywhere however the setting was saved.
        for page in SpherePage
        if page in sphere.enabled_pages
    ]


def sites(request: RootRepositoryRequest) -> SitesContextData:
    # Context processor may run during error handling before middleware completes
    if not hasattr(request, "context") or not hasattr(
        request, "di"
    ):  # pragma: no cover
        return SitesContextData(
            root_site=None,
            current_site=None,
            current_sphere=None,
            is_root_sphere=True,
            has_panel_access=False,
            sphere_page_nav=[],
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
        root_site=root_sphere.site,
        current_site=current_sphere.site,
        current_sphere=current_sphere,
        is_root_sphere=is_root_sphere,
        has_panel_access=has_panel_access(request),
        sphere_page_nav=_sphere_page_nav(request, current_sphere),
    )


def support(_request: HttpRequest) -> dict[str, str]:
    return {"SUPPORT_EMAIL": settings.SUPPORT_EMAIL}


class PosthogConfig(TypedDict):
    api_key: str
    environment: str
    host: str
    # Derived from the URLconf so the browser redacts the same segments the
    # server does, rather than keeping its own copy of the route list.
    redaction_rules: list[list[str]]
    user_id: str | None


class AnalyticsContextData(TypedDict):
    posthog_config: PosthogConfig | None


def analytics(request: HttpRequest) -> AnalyticsContextData:
    if not settings.POSTHOG_API_KEY:
        return AnalyticsContextData(posthog_config=None)
    # Identify by pk, not slug: a slug follows a rename and would split one
    # person across two distinct_ids. request.user rather than the profile
    # service — the auth middleware already resolved it, so this costs no
    # extra query. distinct_id namespaces it per deployment so staging and
    # production cannot land on the same person.
    user = getattr(request, "user", None)
    return AnalyticsContextData(
        posthog_config=PosthogConfig(
            api_key=settings.POSTHOG_API_KEY,
            host=settings.POSTHOG_HOST,
            user_id=(
                identity.distinct_id(user.pk)
                if user is not None and user.is_authenticated
                else None
            ),
            environment=identity.environment(),
            redaction_rules=redaction.client_patterns(),
        )
    )


def static_version(_request: HttpRequest) -> dict[str, str]:
    return {
        "COMMIT_SHA": settings.COMMIT_SHA,
        "STATIC_VERSION": settings.STATIC_VERSION,
    }


class CurrentUserContextData(TypedDict):
    current_user_info: NotRequired[UserInfo]
    current_user: UserDTO | None
    navbar_notifications: NotRequired[NavbarNotificationsDTO]


def current_user(request: RootRepositoryRequest) -> CurrentUserContextData:
    # Context processor may run during error handling before middleware completes
    if (
        not hasattr(request, "context")
        or not hasattr(request, "di")
        or not request.context.current_user_slug
    ):
        return CurrentUserContextData(current_user=None)

    user_dto = request.services.profile.read(request.context.current_user_slug)
    return CurrentUserContextData(
        current_user=user_dto,
        current_user_info=UserInfo.from_user_dto(
            user_dto, gravatar_url=request.di.gravatar_url
        ),
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
