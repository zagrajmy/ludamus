from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.sphere.roles import ROLE_COPY
from ludamus.pacts.multiverse import SphereRole

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

register = template.Library()


@register.filter
def role_label(role: str) -> _StrPromise:
    return ROLE_COPY[SphereRole(role)].label


@register.filter
def role_duty(role: str) -> _StrPromise:
    return ROLE_COPY[SphereRole(role)].duty
