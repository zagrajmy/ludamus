# The single home of the companion-ownership invariant: a login-less
# companion's slot owner is the leader of their ACTIVE party. A leader may
# lead several parties and a real member may belong to many, but a companion
# sits in exactly one (the app-level invariant from RFC 0001) — so membership
# in *a* party led by the leader is ownership, and the queries span all of the
# leader's parties. distinct() and the ACTIVE filter are belt-and-braces:
# companion memberships are always created ACTIVE (INVITED exists only for
# real users) and only once.
from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import PartyMembership, User
from ludamus.pacts.crowd import UserType
from ludamus.pacts.party import PartyMembershipStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet


def active_companions(leader_slug: str) -> QuerySet[User]:
    return User.objects.filter(
        user_type=UserType.CONNECTED,
        party_memberships__party__leader__slug=leader_slug,
        party_memberships__status=PartyMembershipStatus.ACTIVE,
    ).distinct()


def sponsors_by_member(users: Iterable[User]) -> dict[int, User]:
    connected_ids = [u.pk for u in users if u.user_type == UserType.CONNECTED]
    if not connected_ids:
        return {}
    memberships = PartyMembership.objects.filter(
        member_id__in=connected_ids, status=PartyMembershipStatus.ACTIVE
    ).select_related("party__leader")
    return {m.member_id: m.party.leader for m in memberships}


def sponsor_of(user: User) -> User | None:
    return sponsors_by_member([user]).get(user.pk)
