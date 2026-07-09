from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django import template
from django.forms import ChoiceField
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from django import forms

    from ludamus.adapters.web.django.entities import SessionUserParticipationData

register = template.Library()


@dataclass(frozen=True)
class EnrollRowState:
    # Whether the "Include" checkbox starts checked (person is in or holding).
    checked: bool
    # Whether the person cannot be toggled (conflict, no access, or a seat that
    # is theirs to manage) — the box renders disabled with an inline reason.
    disabled: bool
    reason: str
    badge_variant: str
    badge_label: str


_BADGE_CLASSES = {
    "success": "bg-success-bg text-success-text",
    "warning": "bg-warning-bg text-warning-text",
    "danger": "bg-danger-bg text-danger-text",
    "muted": "bg-bg-tertiary text-foreground-secondary",
}


def _badge(data: SessionUserParticipationData) -> tuple[str, str]:
    if data.user_enrolled:
        return "success", _("Already enrolled")
    if data.seat_held:
        return "warning", _("Seat held — awaiting their approval")
    if data.offer_pending:
        return "warning", _("Spot offered")
    if data.user_waiting:
        return "warning", _("On the waiting list")
    if data.has_time_conflict:
        return "danger", _("Time conflict")
    if data.membership.blocked:
        return "muted", _("Access required")
    return "muted", _("Available")


@register.simple_tag
def enroll_row_state(
    form: forms.Form, data: SessionUserParticipationData
) -> EnrollRowState:
    field = form.fields.get(f"user_{data.user.pk}")
    choices = (
        {
            value
            for value in ("enroll", "waitlist", "cancel")
            if field.valid_value(value)
        }
        if isinstance(field, ChoiceField)
        else set()
    )
    membership = data.membership
    in_or_holding = (
        data.user_enrolled or data.user_waiting or data.seat_held or data.offer_pending
    )
    can_cancel = "cancel" in choices
    includable = "enroll" in choices or "waitlist" in choices
    variant, label = _badge(data)

    if in_or_holding:
        # A seat that belongs to the person (a member's own confirmed/waiting
        # place) offers no cancel choice, so the viewer cannot toggle it.
        disabled = not can_cancel
        reason = _("They manage their own enrollment") if disabled else ""
        return EnrollRowState(
            checked=True,
            disabled=disabled,
            reason=reason,
            badge_variant=variant,
            badge_label=label,
        )

    if data.has_time_conflict:
        reason = _("Time conflict")
    elif membership.blocked or (membership.is_member and not includable):
        reason = _("Access required")
    elif not includable:
        reason = _("Enrollment not available")
    else:
        reason = ""
    return EnrollRowState(
        checked=False,
        disabled=bool(reason),
        reason=reason,
        badge_variant=variant,
        badge_label=label,
    )


@register.filter
def badge_classes(variant: str) -> str:
    return _BADGE_CLASSES.get(variant, _BADGE_CLASSES["muted"])
