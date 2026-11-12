from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.staff.forms import (
    ACTION_LABELS,
    GROUND_LABELS,
    KIND_LABELS,
)
from ludamus.pacts.staff_cases import ModerationAction, ModerationGround, StaffCaseKind

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

register = template.Library()


@register.filter
def kind_label(kind: str) -> _StrPromise:
    return KIND_LABELS[StaffCaseKind(kind)]


@register.filter
def action_label(action: str) -> _StrPromise:
    return ACTION_LABELS[ModerationAction(action)]


@register.filter
def ground_label(ground: str) -> _StrPromise:
    return GROUND_LABELS[ModerationGround(ground)]
