from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.staff.forms import (
    DECISION_LABELS,
    GROUND_LABELS,
    KIND_LABELS,
)
from ludamus.pacts.moderation import ModerationDecision, ModerationGround
from ludamus.pacts.staff_cases import CaseKind

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

register = template.Library()


@register.filter
def kind_label(kind: str) -> _StrPromise:
    return KIND_LABELS[CaseKind(kind)]


@register.filter
def decision_label(decision: str) -> _StrPromise:
    return DECISION_LABELS[ModerationDecision(decision)]


@register.filter
def ground_label(ground: str) -> _StrPromise:
    return GROUND_LABELS[ModerationGround(ground)]
