# The single home of the companion-ownership invariant: a login-less
# companion's slot owner is their manager. Party membership is optional and
# only means the companion is part of that party, not that the companion exists.
from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import User
from ludamus.pacts.crowd import UserType

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet


def active_companions(leader_slug: str) -> QuerySet[User]:
    return User.objects.filter(user_type=UserType.CONNECTED, manager__slug=leader_slug)


def sponsors_by_member(users: Iterable[User]) -> dict[int, User]:
    companion_ids = [u.pk for u in users if u.user_type == UserType.CONNECTED]
    if not companion_ids:
        return {}
    companions = User.objects.filter(
        pk__in=companion_ids, manager__isnull=False
    ).select_related("manager")
    return {
        companion.pk: companion.manager
        for companion in companions
        if companion.manager is not None
    }


def sponsor_of(user: User) -> User | None:
    return sponsors_by_member([user]).get(user.pk)
