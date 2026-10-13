"""How each sphere role is named and explained to people.

One table for every page that shows a role, so a role reads the same on the
Team page, the invitation form and the join page, and a new role cannot fall
through to another role's wording.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from django.utils.translation import gettext_lazy as _

from ludamus.pacts.multiverse import SphereRole

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.utils.functional import _StrPromise


class RoleCopy(NamedTuple):
    label: _StrPromise
    # The invitation form's radio: the role and its reach in one line.
    choice: _StrPromise
    # What accepting means, shown to the invitee before they do.
    duty: _StrPromise


ROLE_COPY: Mapping[SphereRole, RoleCopy] = MappingProxyType(
    {
        SphereRole.MANAGER: RoleCopy(
            label=_("Manager"),
            choice=_("Manager: runs the panel and everything in it"),
            duty=_(
                "Managers run the sphere's panel: events, programme, settings "
                "and the team itself."
            ),
        ),
        SphereRole.COMMS: RoleCopy(
            label=_("Comms"),
            choice=_("Comms: sees the whole panel, changes only the Errata checklist"),
            duty=_(
                "Comms people see the sphere's panel and tick off schedule "
                "changes on the Errata page once they've announced them. They "
                "change nothing else."
            ),
        ),
    }
)
