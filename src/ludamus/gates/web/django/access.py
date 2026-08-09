from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Protocol

from ludamus.pacts.multiverse import Capability, SphereRole

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
    def method(self) -> str | None: ...
    @property
    def user(self) -> _UserLike: ...
    @property
    def context(self) -> RequestContext: ...
    @property
    def services(self) -> ServicesProtocol: ...


class PanelAccess(Enum):
    NONE = auto()
    COMMS = auto()
    MANAGER = auto()
    SUPERUSER = auto()


_ROLE_ACCESS = {
    SphereRole.MANAGER: PanelAccess.MANAGER,
    SphereRole.COMMS: PanelAccess.COMMS,
}

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def panel_access(request: _RequestWithServices) -> PanelAccess:
    user_slug = request.context.current_user_slug
    if (
        request.user.is_authenticated
        and user_slug
        and (
            role := request.services.sphere_panel.manager_role(
                request.context.current_sphere_id, user_slug
            )
        )
    ):
        return _ROLE_ACCESS[role]
    if request.user.is_superuser:
        return PanelAccess.SUPERUSER
    return PanelAccess.NONE


def has_panel_access(request: _RequestWithServices) -> bool:
    return panel_access(request) is not PanelAccess.NONE


def passes_panel_access(
    request: _RequestWithServices, *, write_capability: Capability
) -> bool:
    # A cheap door, not the authority: any sphere role may read a panel page,
    # and changing one needs the capability the page stands for. The service
    # performing the operation checks it again, which is what binds a caller
    # arriving by CLI or MCP, and what keeps a view that dispatches several
    # operations from handing all of them to whoever may do one.
    if not has_panel_access(request):
        return False
    # Superusers before roles: `panel_access` reports the sphere role first, so
    # a superuser who also holds a narrow one would otherwise be demoted by it.
    if request.method in SAFE_METHODS or request.user.is_superuser:
        return True
    if not (user_slug := request.context.current_user_slug):
        return False
    return request.services.sphere_panel.can(
        sphere_id=request.context.current_sphere_id,
        user_slug=user_slug,
        capability=write_capability,
    )
