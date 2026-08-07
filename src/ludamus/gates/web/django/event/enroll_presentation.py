from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext as _


@dataclass(frozen=True)
class SeatBadge:
    # `tone` is a design-system name the template maps to classes, the same
    # shape the enroll_select rows use for their status dots.
    tone: str
    label: str
    icon: str


@dataclass(frozen=True)
class EnrollActions:
    # What the one-click form posts, and how its button reads. The template
    # renders these — it never decides which action the viewer gets.
    submit_value: str
    submit_label: str
    submit_icon: str
    # The plain join is the footer's primary action; every other one is
    # secondary, including joining a waiting list.
    is_primary: bool = False
    # Set only when the viewer already holds a seat or a waiting place. It
    # names that state and picks the layout: a standalone button next to a
    # link, rather than the split button that offers a way in.
    badge: SeatBadge | None = None
    # Empty when the step needs no warning.
    confirm: str = ""
    # Label for the segment leading to the group page.
    group_label: str = ""


def _cancel_confirm(*, is_enrollment_available: bool, is_full: bool) -> str:
    if is_enrollment_available:
        if is_full:
            return _(
                "This session is full — cancelling hands your seat to the next "
                "person waiting. Cancel anyway?"
            )
        return ""
    if is_full:
        return _(
            "Enrollment is closed — your seat goes to the next person waiting "
            "and you cannot take it back. Cancel anyway?"
        )
    return _(
        "Enrollment is closed — once you give up your seat you cannot take it "
        "back. Cancel anyway?"
    )


def _leave_confirm(*, is_enrollment_available: bool) -> str:
    if is_enrollment_available:
        return ""
    return _(
        "Enrollment is closed — once you leave the waiting list you cannot "
        "rejoin it. Leave anyway?"
    )


def _group_label(*, is_enrollment_available: bool) -> str:
    if is_enrollment_available:
        return _("Enroll with others…")
    # Seats booked for companions and party members can only be released on the
    # group page, so it stays reachable after the window shuts.
    return _("Manage the seats you booked for others…")


def build_enroll_actions(
    *,
    is_enrollment_available: bool,
    is_ended: bool,
    # An unlimited session is never full, so capacity needs no second flag.
    is_full: bool,
    user_enrolled: bool,
    user_waiting: bool,
) -> EnrollActions | None:
    # A shut window hides the ways *in*, never the way out: the seat of someone
    # who cannot attend belongs to the next person waiting. Once the session is
    # over there is nothing left to hand over. `is_ended` is deliberately not
    # consulted while a window is open — an organizer who leaves one open past
    # the end time keeps the controls that go with it.
    if not is_enrollment_available and (
        is_ended or not (user_enrolled or user_waiting)
    ):
        return None
    group_label = _group_label(is_enrollment_available=is_enrollment_available)
    if user_enrolled:
        return EnrollActions(
            submit_value="cancel",
            submit_label=_("Cancel"),
            submit_icon="x-mark",
            badge=SeatBadge(
                tone="success", label=_("You're enrolled"), icon="check-circle"
            ),
            confirm=_cancel_confirm(
                is_enrollment_available=is_enrollment_available, is_full=is_full
            ),
            group_label=group_label,
        )
    if user_waiting:
        return EnrollActions(
            submit_value="cancel",
            submit_label=_("Leave"),
            submit_icon="x-mark",
            badge=SeatBadge(
                tone="warning", label=_("On the waiting list"), icon="clock"
            ),
            confirm=_leave_confirm(is_enrollment_available=is_enrollment_available),
            group_label=group_label,
        )
    # Past this point the window is open, so `group_label` invites others in.
    if is_full:
        return EnrollActions(
            submit_value="waitlist",
            submit_label=_("Join waiting list"),
            submit_icon="clock",
            group_label=group_label,
        )
    return EnrollActions(
        submit_value="enroll",
        submit_label=_("Enroll"),
        submit_icon="user-plus",
        is_primary=True,
        group_label=group_label,
    )
