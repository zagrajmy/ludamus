from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ludamus.pacts.multiverse import Capability, SphereRole
    from ludamus.pacts.services import RequestContext, ServicesProtocol


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


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class PanelAccess:
    """What one request may do in the current sphere — one role lookup."""

    role: SphereRole | None
    capabilities: frozenset[Capability]
    is_superuser: bool

    @property
    def granted(self) -> bool:
        return self.role is not None or self.is_superuser

    def allows(self, capability: Capability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class _AccessMemo:
    key: tuple[bool, str | None, int]
    access: PanelAccess


# NOTE: the role lookup is an uncached query, and one panel request asks it from
# the page check, the refusal and the sidebar's context processor.
_MEMO_ATTR = "_ludamus_panel_access"


def panel_access(request: _RequestWithServices) -> PanelAccess:
    key = (
        request.user.is_authenticated,
        request.context.current_user_slug,
        request.context.current_sphere_id,
    )
    memo = getattr(request, _MEMO_ATTR, None)
    if isinstance(memo, _AccessMemo) and memo.key == key:
        return memo.access
    access = _resolve_panel_access(request)
    setattr(request, _MEMO_ATTR, _AccessMemo(key=key, access=access))
    return access


def _resolve_panel_access(request: _RequestWithServices) -> PanelAccess:
    sphere_access = None
    if request.user.is_authenticated and (
        user_slug := request.context.current_user_slug
    ):
        sphere_access = request.services.sphere_panel.access(
            request.context.current_sphere_id,
            user_slug,
            is_superuser=request.user.is_superuser,
        )
    return PanelAccess(
        role=sphere_access.role if sphere_access else None,
        capabilities=sphere_access.capabilities if sphere_access else frozenset(),
        is_superuser=request.user.is_superuser,
    )


def has_panel_access(request: _RequestWithServices) -> bool:
    return panel_access(request).granted


def passes_panel_access(
    request: _RequestWithServices, *, write_capability: Capability
) -> bool:
    # The authority for panel writes: any sphere role may read a panel page,
    # and changing one needs the capability the page stands for. Callers that
    # never reach a panel view are gated where they arrive instead —
    # `ProposalAcceptanceService` for CLI and in-app acceptance,
    # `authenticate_organizer` for MCP.
    access = panel_access(request)
    if not access.granted:
        return False
    return request.method in SAFE_METHODS or access.allows(write_capability)
