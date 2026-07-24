from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django import template
from django.forms import ChoiceField
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from django import forms

    from ludamus.gates.web.django.chronology.enrollment_presentation import (
        SessionUserParticipationData,
    )
    from ludamus.links.db.django.models import Session

register = template.Library()


@dataclass(frozen=True)
class Badge:
    variant: str
    label: str


@dataclass(frozen=True)
class EnrollRowState:
    # Whether the person is currently in or holding a seat (drives the
    # projection's data-current-in and the "no change" diffing).
    checked: bool
    # Whether the person cannot be toggled (conflict, no access, or a seat that
    # is theirs to manage) — the box renders disabled with an inline reason.
    disabled: bool
    reason: str
    badge: Badge
    # The form field this row posts as (user_<pk>).
    field_name: str = ""
    # How the Include box actually renders: current reality, plus the strong
    # default — the viewer's own box starts ticked whenever they can join, so
    # the common solo case is one click.
    box_checked: bool = False
    # Unticking this person frees a confirmed seat (CONFIRMED, or an OFFERED
    # held seat / pending offer) — a waiting-list place frees nothing. Feeds
    # the client-side projection so it counts exactly like the server routing.
    occupies_seat: bool = False


# Status renders as a small colored dot beside neutral text — never text on a
# tinted chip.
_BADGE_CLASSES = {
    "success": "bg-success",
    "warning": "bg-warning",
    "danger": "bg-danger",
    "muted": "bg-foreground-muted",
}


def _badge(data: SessionUserParticipationData) -> Badge:
    if data.user_enrolled:
        return Badge("success", _("Already enrolled"))
    if data.seat_held:
        return Badge("warning", _("Seat held — awaiting their approval"))
    if data.offer_pending:
        return Badge("warning", _("Spot offered"))
    if data.user_waiting:
        return Badge("warning", _("On the waiting list"))
    if data.has_time_conflict:
        return Badge("danger", _("Time conflict"))
    if data.membership.blocked:
        return Badge("muted", _("Access required"))
    return Badge("muted", _("Available"))


@register.simple_tag
def enroll_row_state(
    *,
    form: forms.Form,
    data: SessionUserParticipationData,
    viewer_pk: int | None = None,
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
    badge = _badge(data)
    field_name = f"user_{data.user.pk}"

    if in_or_holding:
        # A seat that belongs to the person (a member's own confirmed/waiting
        # place) offers no cancel choice, so the viewer cannot toggle it.
        disabled = not can_cancel
        reason = _("They manage their own enrollment") if disabled else ""
        return EnrollRowState(
            checked=True,
            disabled=disabled,
            reason=reason,
            badge=badge,
            field_name=field_name,
            box_checked=True,
            occupies_seat=(data.user_enrolled or data.seat_held or data.offer_pending),
        )

    if data.has_time_conflict:
        reason = _("Time conflict")
    elif membership.blocked or (membership.is_member and not includable):
        reason = _("Access required")
    elif not includable:
        reason = _("Enrollment not available")
    else:
        reason = ""
    disabled = bool(reason)
    return EnrollRowState(
        checked=False,
        disabled=disabled,
        reason=reason,
        badge=badge,
        field_name=field_name,
        box_checked=data.user.pk == viewer_pk and not disabled,
    )


@register.filter
def badge_classes(variant: str) -> str:
    return _BADGE_CLASSES.get(variant, _BADGE_CLASSES["muted"])


@register.simple_tag
def enroll_seats_left(session: Session) -> int | None:
    # None means unlimited. Mirrors EnrollmentConfig.get_available_slots for the
    # most liberal config: effective_participants_limit already applies that
    # config's percentage, and enrolled_count counts the occupying statuses.
    if session.participants_limit == 0:
        return None
    return max(0, session.effective_participants_limit - session.enrolled_count)
