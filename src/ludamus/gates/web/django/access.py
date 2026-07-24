from __future__ import annotations

from enum import Enum
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


class PanelAccess(Enum):
    NONE = "none"
    MANAGER = "manager"
    SUPERUSER = "superuser"


def panel_access(request: _RequestWithServices) -> PanelAccess:
    user_slug = request.context.current_user_slug
    if (
        request.user.is_authenticated
        and user_slug
        and request.services.sphere_panel.is_manager(
            request.context.current_sphere_id, user_slug
        )
    ):
        return PanelAccess.MANAGER
    if request.user.is_superuser:
        return PanelAccess.SUPERUSER
    return PanelAccess.NONE


def has_panel_access(request: _RequestWithServices) -> bool:
    return panel_access(request) is not PanelAccess.NONE
