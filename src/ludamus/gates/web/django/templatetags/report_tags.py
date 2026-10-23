from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.report import KIND_LABELS, REASON_LABELS
from ludamus.pacts.report import ReportedContentKind, ReportReason

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

register = template.Library()


@register.filter
def reason_label(reason: str) -> _StrPromise:
    return REASON_LABELS[ReportReason(reason)]


@register.filter
def kind_label(kind: str) -> _StrPromise:
    return KIND_LABELS[ReportedContentKind(kind)]
