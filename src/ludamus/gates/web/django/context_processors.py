from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from django.conf import settings

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.entities import UserInfo

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.adapters.web.django.middlewares import RootRepositoryRequest
    from ludamus.pacts import SiteDTO, SphereDTO
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.enrollment import NavbarNotificationsDTO


class SitesContextData(TypedDict):
    root_site: SiteDTO | None
    current_site: SiteDTO | None
    current_sphere: SphereDTO | None
    has_panel_access: bool


def sites(request: RootRepositoryRequest) -> SitesContextData:
    # Context processor may run during error handling before middleware completes
    if not hasattr(request, "context") or not hasattr(
        request, "di"
    ):  # pragma: no cover
        return SitesContextData(
            root_site=None,
            current_site=None,
            current_sphere=None,
            has_panel_access=False,
        )

    sites_service = request.services.sites
    root_sphere = sites_service.read(request.context.root_sphere_id)
    current_sphere = (
        root_sphere
        if request.context.current_sphere_id == request.context.root_sphere_id
        else sites_service.read(request.context.current_sphere_id)
    )

    return SitesContextData(
        root_site=root_sphere.site,
        current_site=current_sphere.site,
        current_sphere=current_sphere,
        has_panel_access=has_panel_access(request),
    )


def support(
    request: HttpRequest,  # ruff: ignore[unused-function-argument]
) -> dict[str, str]:
    return {"SUPPORT_EMAIL": settings.SUPPORT_EMAIL}


def static_version(
    request: HttpRequest,  # ruff: ignore[unused-function-argument]
) -> dict[str, str]:
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
