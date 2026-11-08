from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from ludamus.pacts.sphere import Capability, SphereAccessDTO, SphereRole

if TYPE_CHECKING:
    from collections.abc import Mapping

ROLE_CAPABILITIES: Mapping[SphereRole, frozenset[Capability]] = MappingProxyType(
    {
        SphereRole.MANAGER: frozenset(Capability),
        # Reads the panel and changes nothing but the errata feed, which is
        # the job: announcing agenda changes and ticking off the announced.
        SphereRole.COMMS: frozenset({Capability.ERRATUM_ACK}),
    }
)


def sphere_access(role: SphereRole | None, *, is_superuser: bool) -> SphereAccessDTO:
    # Superusers before roles: a superuser who also holds a narrow sphere role
    # must not be demoted by it.
    if is_superuser:
        return SphereAccessDTO(role=role, capabilities=frozenset(Capability))
    return SphereAccessDTO(
        role=role, capabilities=ROLE_CAPABILITIES[role] if role else frozenset()
    )


# Long enough to reach someone over a weekend; short enough that a link
# forgotten in a chat log stops granting a role on its own.
INVITATION_LIFETIME = timedelta(days=7)
