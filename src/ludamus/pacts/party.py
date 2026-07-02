"""Party subdomain contracts — enums backing the step-1 tables. See RFC 0001."""

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
