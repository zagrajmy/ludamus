"""Party subdomain contracts.

A Party is the group that enrolls together — ephemeral but reusable (a drużyna,
not a Guild). It is the unit of whole-party waitlist promotion. See RFC 0001.

Step 1 (groundwork) needs only the enums that back the model fields; DTOs and
repository/service protocols arrive with the later steps.
"""

from __future__ import annotations

from enum import StrEnum


class PartyConsentMode(StrEnum):
    # How an enrollment reaches this member: taken-and-notified, or held until
    # they accept. A login-less companion is always ACCEPT_BY_DEFAULT; a real
    # user defaults to ACCEPT_INVITES and may grant the leader power of attorney.
    ACCEPT_BY_DEFAULT = "accept_by_default"
    ACCEPT_INVITES = "accept_invites"


class PartyMembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
