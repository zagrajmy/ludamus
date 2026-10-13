from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from ludamus.pacts.multiverse import Capability, SphereRole

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

# Long enough to reach someone over a weekend; short enough that a link
# forgotten in a chat log stops granting a role on its own.
INVITATION_LIFETIME = timedelta(days=7)
