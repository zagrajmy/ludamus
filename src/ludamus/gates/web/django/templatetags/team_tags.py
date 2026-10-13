from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.timesince import timeuntil

from ludamus.gates.web.django.sphere.roles import ROLE_COPY
from ludamus.pacts.multiverse import SphereRole

if TYPE_CHECKING:
    from datetime import datetime

    from django.utils.functional import _StrPromise

register = template.Library()


@register.filter
def role_label(role: str) -> _StrPromise:
    return ROLE_COPY[SphereRole(role)].label


@register.filter
def role_duty(role: str) -> _StrPromise:
    return ROLE_COPY[SphereRole(role)].duty


@register.filter
def expires_in(moment: datetime) -> str:
    # A week-long link needs the day, not the hour: "6 days", not
    # "6 days, 23 hours". The exact time sits in the element's title.
    return timeuntil(moment, depth=1)
