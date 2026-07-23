"""Shared panel-access policy: sphere managers and superusers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ludamus.pacts import RequestContext
    from ludamus.pacts.services import ServicesProtocol


class _UserLike(Protocol):
    @property
    def is_superuser(self) -> bool: ...
    @property
    def is_authenticated(self) -> bool: ...


class _RequestWithServices(Protocol):
    @property
    def user(self) -> _UserLike: ...
    @property
    def context(self) -> RequestContext: ...
    @property
    def services(self) -> ServicesProtocol: ...


def has_panel_access(request: _RequestWithServices) -> bool:
    if request.user.is_superuser:
        return True
    if not request.user.is_authenticated or not request.context.current_user_slug:
        return False
    return request.services.sphere_panel.is_manager(
        request.context.current_sphere_id, request.context.current_user_slug
    )
