from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from django.conf import settings

from ludamus.gates.web.django.entities import UserInfo

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ludamus.adapters.web.django.middlewares import RootRepositoryRequest
    from ludamus.pacts import SiteDTO, SphereDTO, UserDTO


class SitesContextData(TypedDict):
    root_site: SiteDTO | None
    current_site: SiteDTO | None
    current_sphere: SphereDTO | None
    is_sphere_manager: bool


def sites(request: RootRepositoryRequest) -> SitesContextData:
    # Context processor may run during error handling before middleware completes
    if not hasattr(request, "context") or not hasattr(
        request, "di"
    ):  # pragma: no cover
        return SitesContextData(
            root_site=None,
            current_site=None,
            current_sphere=None,
            is_sphere_manager=False,
        )

    sphere_repository = request.di.uow.spheres
    root_sphere = sphere_repository.read(request.context.root_sphere_id)
    current_sphere = sphere_repository.read(request.context.current_sphere_id)

    is_sphere_manager = False
    if request.user.is_authenticated and request.context.current_user_slug:
        is_sphere_manager = sphere_repository.is_manager(
            current_sphere.pk, request.context.current_user_slug
        )

    return SitesContextData(
        root_site=sphere_repository.read_site(root_sphere.pk),
        current_site=sphere_repository.read_site(current_sphere.pk),
        current_sphere=current_sphere,
        is_sphere_manager=is_sphere_manager,
    )


def support(request: HttpRequest) -> dict[str, str]:  # noqa: ARG001
    return {"SUPPORT_EMAIL": settings.SUPPORT_EMAIL}


def static_version(request: HttpRequest) -> dict[str, str]:  # noqa: ARG001
    return {"STATIC_VERSION": settings.STATIC_VERSION}


class CurrentUserContextData(TypedDict):
    current_user_info: NotRequired[UserInfo]
    current_user: UserDTO | None


def current_user(request: RootRepositoryRequest) -> CurrentUserContextData:
    # Context processor may run during error handling before middleware completes
    if (
        not hasattr(request, "context")
        or not hasattr(request, "di")
        or not request.context.current_user_slug
    ):
        return CurrentUserContextData(current_user=None)

    user_dto = request.di.uow.active_users.read(request.context.current_user_slug)
    return CurrentUserContextData(
        current_user=user_dto,
        current_user_info=UserInfo.from_user_dto(
            user_dto, gravatar_url=request.di.gravatar_url
        ),
    )
