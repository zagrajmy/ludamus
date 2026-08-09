"""Who may do what in a sphere — the whole policy, in one table."""

from types import MappingProxyType
from typing import TYPE_CHECKING

from ludamus.pacts.multiverse import Capability, SphereRole

if TYPE_CHECKING:
    from collections.abc import Mapping

ROLE_CAPABILITIES: Mapping[SphereRole, frozenset[Capability]] = MappingProxyType(
    {
        SphereRole.MANAGER: frozenset(Capability),
        # Reads the panel, changes nothing. Publishing errata lands here when
        # that page ships.
        SphereRole.COMMS: frozenset(),
    }
)
